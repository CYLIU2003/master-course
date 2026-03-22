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


def _bootstrap_dataset_id(bootstrap: Dict[str, Any], fallback: str) -> str:
    return str(
        (bootstrap.get("feed_context") or {}).get("datasetId")
        or (bootstrap.get("scenario_overlay") or {}).get("dataset_id")
        or fallback
    )


def _scenario_id_for_doc(doc: Dict[str, Any], dataset_id: str) -> str:
    meta = dict(doc.get("meta") or {})
    return str(meta.get("id") or f"app-master:{dataset_id}")


def _random_seed_for_doc(doc: Dict[str, Any]) -> int:
    meta = dict(doc.get("meta") or {})
    overlay = dict(doc.get("scenario_overlay") or {})
    for value in (
        overlay.get("random_seed"),
        overlay.get("randomSeed"),
        meta.get("randomSeed"),
    ):
        try:
            if value not in (None, ""):
                return int(value)
        except (TypeError, ValueError):
            continue
    return 42


def _merge_depots(
    current: list[Dict[str, Any]],
    fresh: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    preserve_keys = {
        "name",
        "location",
        "lat",
        "lon",
        "normalChargerCount",
        "normalChargerPowerKw",
        "fastChargerCount",
        "fastChargerPowerKw",
        "hasFuelFacility",
        "parkingCapacity",
        "overnightCharging",
        "notes",
        "enabled",
    }
    current_by_id = {
        str(item.get("id") or item.get("depotId") or "").strip(): dict(item)
        for item in current
        if str(item.get("id") or item.get("depotId") or "").strip()
    }
    merged: list[Dict[str, Any]] = []
    for item in fresh:
        depot_id = str(item.get("id") or item.get("depotId") or "").strip()
        merged_item = dict(item)
        current_item = current_by_id.get(depot_id) or {}
        for key in preserve_keys:
            if key in current_item and current_item.get(key) is not None:
                merged_item[key] = current_item.get(key)
        merged.append(merged_item)
    return merged


def _merge_routes(
    current: list[Dict[str, Any]],
    fresh: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    preserve_keys = {
        "enabled",
        "color",
        "routeVariantTypeManual",
        "canonicalDirectionManual",
    }
    current_by_id = {
        str(item.get("id") or "").strip(): dict(item)
        for item in current
        if str(item.get("id") or "").strip()
    }
    merged: list[Dict[str, Any]] = []
    for item in fresh:
        route_id = str(item.get("id") or "").strip()
        merged_item = dict(item)
        current_item = current_by_id.get(route_id) or {}
        for key in preserve_keys:
            if key in current_item and current_item.get(key) is not None:
                merged_item[key] = current_item.get(key)
        merged.append(merged_item)
    return merged


def _merge_pair_items(
    current: list[Dict[str, Any]],
    fresh: list[Dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
) -> list[Dict[str, Any]]:
    current_by_key = {}
    for item in current:
        key = tuple(str(item.get(field) or "").strip() for field in key_fields)
        if all(key):
            current_by_key[key] = dict(item)
    merged: list[Dict[str, Any]] = []
    for item in fresh:
        key = tuple(str(item.get(field) or "").strip() for field in key_fields)
        if not all(key):
            continue
        merged_item = dict(item)
        if key in current_by_key:
            merged_item.update(current_by_key[key])
        merged.append(merged_item)
    return merged


def _filter_pair_items(
    items: list[Dict[str, Any]],
    *,
    route_ids: set[str],
    depot_ids: Optional[set[str]] = None,
    vehicle_ids: Optional[set[str]] = None,
) -> list[Dict[str, Any]]:
    filtered: list[Dict[str, Any]] = []
    for item in items:
        route_id = str(item.get("routeId") or "").strip()
        if route_id not in route_ids:
            continue
        if depot_ids is not None and str(item.get("depotId") or "").strip() not in depot_ids:
            continue
        if vehicle_ids is not None and str(item.get("vehicleId") or "").strip() not in vehicle_ids:
            continue
        filtered.append(dict(item))
    return filtered


def _merged_dispatch_scope(
    current_scope: Dict[str, Any],
    bootstrap_scope: Dict[str, Any],
    *,
    valid_depot_ids: list[str],
    valid_route_ids: list[str],
) -> Dict[str, Any]:
    valid_depot_set = set(valid_depot_ids)
    valid_route_set = set(valid_route_ids)
    current_depot_selection = dict(current_scope.get("depotSelection") or {})
    current_route_selection = dict(current_scope.get("routeSelection") or {})
    current_service_selection = dict(current_scope.get("serviceSelection") or {})

    preserved_depot_ids = [
        str(value)
        for value in list(current_depot_selection.get("depotIds") or [])
        if str(value or "").strip() in valid_depot_set
    ]
    primary_depot_id = str(current_depot_selection.get("primaryDepotId") or "").strip()
    if primary_depot_id and primary_depot_id in valid_depot_set and primary_depot_id not in preserved_depot_ids:
        preserved_depot_ids.insert(0, primary_depot_id)

    preserved_route_ids = [
        str(value)
        for value in list(current_route_selection.get("includeRouteIds") or [])
        if str(value or "").strip() in valid_route_set
    ]

    merged_scope = copy.deepcopy(bootstrap_scope or {})
    merged_scope["scopeId"] = current_scope.get("scopeId", merged_scope.get("scopeId"))
    merged_scope["operatorId"] = current_scope.get("operatorId", merged_scope.get("operatorId"))
    merged_scope["datasetVersion"] = bootstrap_scope.get("datasetVersion", current_scope.get("datasetVersion"))
    merged_scope["tripSelection"] = {
        **dict(bootstrap_scope.get("tripSelection") or {}),
        **dict(current_scope.get("tripSelection") or {}),
    }
    merged_scope["serviceSelection"] = (
        dict(current_service_selection)
        if current_service_selection
        else dict(bootstrap_scope.get("serviceSelection") or {})
    )
    merged_scope["allowIntraDepotRouteSwap"] = bool(
        current_scope.get(
            "allowIntraDepotRouteSwap",
            bootstrap_scope.get("allowIntraDepotRouteSwap", False),
        )
    )
    merged_scope["allowInterDepotSwap"] = bool(
        current_scope.get(
            "allowInterDepotSwap",
            bootstrap_scope.get("allowInterDepotSwap", False),
        )
    )
    merged_scope["depotSelection"] = {
        "mode": "include",
        "depotIds": preserved_depot_ids,
        "primaryDepotId": preserved_depot_ids[0] if preserved_depot_ids else None,
    }
    merged_scope["routeSelection"] = {
        "mode": "include",
        "includeRouteIds": preserved_route_ids,
        "excludeRouteIds": [],
    }
    merged_scope["depotId"] = preserved_depot_ids[0] if preserved_depot_ids else None
    merged_scope["serviceId"] = str(
        (merged_scope.get("serviceSelection") or {}).get("serviceIds", [current_scope.get("serviceId") or "WEEKDAY"])[0]
    )
    return merged_scope


def _merged_scenario_overlay(
    current_overlay: Dict[str, Any],
    bootstrap_overlay: Dict[str, Any],
    *,
    selected_depot_ids: list[str],
    selected_route_ids: list[str],
) -> Dict[str, Any]:
    merged = dict(bootstrap_overlay or {})
    if current_overlay:
        for key, value in dict(current_overlay).items():
            if key in {"dataset_id", "datasetId", "dataset_version", "datasetVersion", "depot_ids", "route_ids"}:
                continue
            merged[key] = copy.deepcopy(value)
    merged["depot_ids"] = list(selected_depot_ids)
    merged["route_ids"] = list(selected_route_ids)
    return merged


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
    else:
        if (
            target_dataset_id != DEFAULT_DATASET_ID
            and not list(bootstrap.get("trips") or [])
        ):
            fallback = build_dataset_bootstrap(
                DEFAULT_DATASET_ID,
                scenario_id=f"app-master:{DEFAULT_DATASET_ID}",
                random_seed=42,
            )
            if list(fallback.get("trips") or []):
                bootstrap = fallback
                target_dataset_id = DEFAULT_DATASET_ID
    effective_dataset_id = _bootstrap_dataset_id(bootstrap, target_dataset_id)

    return {
        "datasetId": effective_dataset_id,
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

    payload = get_preloaded_master_data(str(target_dataset_id))
    effective_dataset_id = str(payload.get("datasetId") or target_dataset_id).strip() or target_dataset_id
    payload_route_ids = {
        str(item.get("id") or "").strip()
        for item in payload.get("routes") or []
        if str(item.get("id") or "").strip()
    }
    payload_depot_ids = {
        str(item.get("id") or item.get("depotId") or "").strip()
        for item in payload.get("depots") or []
        if str(item.get("id") or item.get("depotId") or "").strip()
    }
    current_route_ids = {
        str(item.get("id") or "").strip()
        for item in current_routes
        if str(item.get("id") or "").strip()
    }
    current_depot_ids = {
        str(item.get("id") or item.get("depotId") or "").strip()
        for item in current_depots
        if str(item.get("id") or item.get("depotId") or "").strip()
    }
    needs_runtime_refresh = (
        effective_dataset_id != str(target_dataset_id)
        or (
            current_route_ids
            and payload_route_ids
            and not current_route_ids.intersection(payload_route_ids)
        )
        or (
            current_route_ids
            and payload_route_ids
            and current_route_ids.issubset(payload_route_ids)
            and len(current_route_ids) < len(payload_route_ids)
        )
        or (
            current_depot_ids
            and payload_depot_ids
            and current_depot_ids.issubset(payload_depot_ids)
            and len(current_depot_ids) < len(payload_depot_ids)
        )
    )

    if needs_runtime_refresh:
        bootstrap = build_dataset_bootstrap(
            effective_dataset_id,
            scenario_id=_scenario_id_for_doc(doc, effective_dataset_id),
            random_seed=_random_seed_for_doc(doc),
        )
        fresh_depots = list(bootstrap.get("depots") or [])
        fresh_routes = list(bootstrap.get("routes") or [])
        bootstrap_scope_depot_ids = [
            str(value).strip()
            for value in list(
                (
                    (bootstrap.get("dispatch_scope") or {}).get("depotSelection") or {}
                ).get("depotIds")
                or []
            )
            if str(value).strip()
        ]
        valid_depot_ids = bootstrap_scope_depot_ids or [
            str(item.get("id") or item.get("depotId") or "").strip()
            for item in fresh_depots
            if str(item.get("id") or item.get("depotId") or "").strip()
        ]
        valid_route_ids = [
            str(item.get("id") or "").strip()
            for item in fresh_routes
            if str(item.get("id") or "").strip()
        ]
        valid_vehicle_ids = {
            str(item.get("id") or "").strip()
            for item in list(doc.get("vehicles") or [])
            if str(item.get("id") or "").strip()
        }
        doc["depots"] = _merge_depots(current_depots, fresh_depots)
        doc["routes"] = _merge_routes(current_routes, fresh_routes)
        doc["route_depot_assignments"] = _merge_pair_items(
            _filter_pair_items(
                list(doc.get("route_depot_assignments") or []),
                route_ids=set(valid_route_ids),
                depot_ids=set(valid_depot_ids),
            ),
            list(bootstrap.get("route_depot_assignments") or []),
            key_fields=("routeId", "depotId"),
        )
        doc["depot_route_permissions"] = _merge_pair_items(
            _filter_pair_items(
                list(doc.get("depot_route_permissions") or []),
                route_ids=set(valid_route_ids),
                depot_ids=set(valid_depot_ids),
            ),
            list(bootstrap.get("depot_route_permissions") or []),
            key_fields=("depotId", "routeId"),
        )
        doc["vehicle_route_permissions"] = _filter_pair_items(
            list(doc.get("vehicle_route_permissions") or []),
            route_ids=set(valid_route_ids),
            vehicle_ids=valid_vehicle_ids,
        )
        if not doc.get("vehicle_templates"):
            doc["vehicle_templates"] = list(
                bootstrap.get("vehicle_templates") or default_vehicle_templates()
            )
        doc["stops"] = list(bootstrap.get("stops") or [])
        if not list(doc.get("calendar") or []):
            doc["calendar"] = list(bootstrap.get("calendar") or [])
        if not list(doc.get("calendar_dates") or []):
            doc["calendar_dates"] = list(bootstrap.get("calendar_dates") or [])
        merged_scope = _merged_dispatch_scope(
            current_scope,
            dict(bootstrap.get("dispatch_scope") or {}),
            valid_depot_ids=valid_depot_ids,
            valid_route_ids=valid_route_ids,
        )
        doc["dispatch_scope"] = merged_scope
        doc["feed_context"] = dict(bootstrap.get("feed_context") or {})
        doc["runtime_features"] = copy.deepcopy(bootstrap.get("runtime_features"))
        doc["scenario_overlay"] = _merged_scenario_overlay(
            dict(doc.get("scenario_overlay") or {}),
            dict(bootstrap.get("scenario_overlay") or {}),
            selected_depot_ids=list((merged_scope.get("depotSelection") or {}).get("depotIds") or []),
            selected_route_ids=list((merged_scope.get("routeSelection") or {}).get("includeRouteIds") or []),
        )
        return True

    if has_core_master_data and current_permissions and not is_full_matrix_allow_all and has_scope_selection:
        return False

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
