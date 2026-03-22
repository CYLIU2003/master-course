"""
bff/routers/scenarios.py

Scenario CRUD + app context + timetable + deadhead/turnaround rules endpoints.

Routes:
  GET    /scenarios                    → list
  GET    /scenarios/default            → get latest scenario metadata (legacy helper)
  POST   /scenarios                    → create
  GET    /scenarios/{id}               → get
  PUT    /scenarios/{id}               → update
  DELETE /scenarios/{id}               → delete
  POST   /scenarios/{id}/duplicate     → duplicate
  POST   /scenarios/{id}/activate      → set active scenario
  GET    /app/context                  → get app context

  GET    /scenarios/{id}/timetable               → get timetable rows (optional ?service_id=)
  PUT    /scenarios/{id}/timetable               → replace timetable rows
  POST   /scenarios/{id}/timetable/import-csv    → import rows from CSV text body
  GET    /scenarios/{id}/timetable/export-csv    → export rows as CSV text body

  GET    /scenarios/{id}/deadhead-rules    → list
  GET    /scenarios/{id}/turnaround-rules  → list
"""

from __future__ import annotations

import csv
import io
import re
from threading import Lock
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from bff.services import research_catalog
from bff.services.service_ids import canonical_service_id
from bff.store import scenario_store as store
from src.dispatch.models import hhmm_to_min
from src.objective_modes import (
    legacy_objective_weights_for_mode,
    normalize_objective_mode,
)
from src.route_family_runtime import (
    normalize_direction,
    normalize_variant_type,
)
from src.tokyu_shard_loader import (
    build_stop_timetable_summary_for_scope,
    build_timetable_summary_for_scope,
    load_trip_rows_for_scope,
    shard_runtime_ready,
)

router = APIRouter(tags=["scenarios"])
_default_scenario_lock = Lock()

# ── CSV column spec ────────────────────────────────────────────
# Canonical column order for import/export
_CSV_COLUMNS = [
    "trip_id",
    "route_id",
    "service_id",
    "direction",
    "origin",
    "destination",
    "departure",
    "arrival",
    "distance_km",
    "allowed_vehicle_types",
]

_MAX_PAGE_LIMIT = 500


def _paginate_items(
    items: List[Dict[str, Any]],
    limit: Optional[int],
    offset: int,
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    if limit is None:
        return items[offset:], None
    bounded_limit = max(1, min(limit, _MAX_PAGE_LIMIT))
    start = max(0, offset)
    end = start + bounded_limit
    return items[start:end], bounded_limit


def _updated_at_from_imports(imports: Dict[str, Any]) -> Optional[str]:
    generated_values = [
        str(meta.get("generatedAt"))
        for meta in (imports or {}).values()
        if isinstance(meta, dict) and meta.get("generatedAt")
    ]
    return max(generated_values) if generated_values else None


def _min_hhmm(values: List[str]) -> Optional[str]:
    usable = [value for value in values if isinstance(value, str) and value.strip()]
    if not usable:
        return None
    return min(usable, key=hhmm_to_min)


def _max_hhmm(values: List[str]) -> Optional[str]:
    usable = [value for value in values if isinstance(value, str) and value.strip()]
    if not usable:
        return None
    return max(usable, key=hhmm_to_min)


_VN_TRIP_RE = re.compile(r"__v\d+$")


def _build_timetable_summary(
    rows: List[Dict[str, Any]],
    imports: Dict[str, Any],
) -> Dict[str, Any]:
    # Exclude __vN GTFS reconciliation duplicates before counting
    rows = [row for row in rows if not _VN_TRIP_RE.search(str(row.get("trip_id") or ""))]
    by_service: Dict[str, Dict[str, Any]] = {}
    by_route: Dict[str, Dict[str, Any]] = {}
    route_service_counts: Dict[str, Dict[str, int]] = {}
    stop_counts: Dict[str, int] = {}

    for row in rows:
        service_id = canonical_service_id(row.get("service_id"))
        route_id = str(row.get("route_id") or "")
        departure = str(row.get("departure") or "")
        arrival = str(row.get("arrival") or "")
        origin = str(row.get("origin") or "")
        destination = str(row.get("destination") or "")
        trip_id = str(row.get("trip_id") or "")

        service_bucket = by_service.setdefault(
            service_id,
            {
                "serviceId": service_id,
                "rowCount": 0,
                "routeIds": set(),
                "departures": [],
                "arrivals": [],
            },
        )
        service_bucket["rowCount"] += 1
        if route_id:
            service_bucket["routeIds"].add(route_id)
        if departure:
            service_bucket["departures"].append(departure)
        if arrival:
            service_bucket["arrivals"].append(arrival)

        route_bucket = by_route.setdefault(
            route_id or "__unknown__",
            {
                "routeId": route_id,
                "rowCount": 0,
                "serviceIds": set(),
                "departures": [],
                "arrivals": [],
                "sampleTripIds": [],
            },
        )
        route_bucket["rowCount"] += 1
        route_bucket["serviceIds"].add(service_id)
        if departure:
            route_bucket["departures"].append(departure)
        if arrival:
            route_bucket["arrivals"].append(arrival)
        if trip_id and len(route_bucket["sampleTripIds"]) < 5:
            route_bucket["sampleTripIds"].append(trip_id)

        route_service_counts.setdefault(service_id, {})
        if route_id:
            route_service_counts[service_id][route_id] = (
                route_service_counts[service_id].get(route_id, 0) + 1
            )

        if origin:
            stop_counts[origin] = stop_counts.get(origin, 0) + 1
        if destination:
            stop_counts[destination] = stop_counts.get(destination, 0) + 1

    service_summaries = sorted(
        [
            {
                "serviceId": bucket["serviceId"],
                "rowCount": bucket["rowCount"],
                "routeCount": len(bucket["routeIds"]),
                "firstDeparture": _min_hhmm(bucket["departures"]),
                "lastArrival": _max_hhmm(bucket["arrivals"]),
            }
            for bucket in by_service.values()
        ],
        key=lambda item: str(item.get("serviceId") or ""),
    )

    route_summaries = sorted(
        [
            {
                "routeId": bucket["routeId"],
                "rowCount": bucket["rowCount"],
                "serviceCount": len(bucket["serviceIds"]),
                "firstDeparture": _min_hhmm(bucket["departures"]),
                "lastArrival": _max_hhmm(bucket["arrivals"]),
                "sampleTripIds": bucket["sampleTripIds"],
            }
            for bucket in by_route.values()
            if bucket["routeId"]
        ],
        key=lambda item: (
            str(item.get("routeId") or ""),
            str(item.get("firstDeparture") or ""),
        ),
    )

    return {
        "totalRows": len(rows),
        "serviceCount": len(service_summaries),
        "routeCount": len(route_summaries),
        "stopCount": len(stop_counts),
        "updatedAt": _updated_at_from_imports(imports),
        "byService": service_summaries,
        "byRoute": route_summaries[:200],
        "routeServiceCounts": route_service_counts,
        "previewTripIds": [
            str(row.get("trip_id") or "")
            for row in rows[: min(100, len(rows))]
            if row.get("trip_id")
        ],
        "imports": imports,
    }


def _build_stop_timetable_summary(
    items: List[Dict[str, Any]],
    imports: Dict[str, Any],
) -> Dict[str, Any]:
    by_service: Dict[str, Dict[str, Any]] = {}
    by_stop: Dict[str, Dict[str, Any]] = {}
    total_entries = 0

    for item in items:
        service_id = canonical_service_id(item.get("service_id"))
        stop_id = str(item.get("stopId") or item.get("stop_id") or "")
        stop_name = str(item.get("stopName") or item.get("stop_name") or stop_id)
        entry_count = len(item.get("items") or [])
        total_entries += entry_count

        service_bucket = by_service.setdefault(
            service_id,
            {
                "serviceId": service_id,
                "timetableCount": 0,
                "entryCount": 0,
                "stopIds": set(),
            },
        )
        service_bucket["timetableCount"] += 1
        service_bucket["entryCount"] += entry_count
        if stop_id:
            service_bucket["stopIds"].add(stop_id)

        stop_bucket = by_stop.setdefault(
            stop_id or "__unknown__",
            {
                "stopId": stop_id,
                "stopName": stop_name,
                "timetableCount": 0,
                "entryCount": 0,
                "serviceIds": set(),
            },
        )
        stop_bucket["timetableCount"] += 1
        stop_bucket["entryCount"] += entry_count
        stop_bucket["serviceIds"].add(service_id)

    return {
        "totalTimetables": len(items),
        "totalEntries": total_entries,
        "serviceCount": len(by_service),
        "stopCount": len([key for key in by_stop.keys() if key != "__unknown__"]),
        "updatedAt": _updated_at_from_imports(imports),
        "byService": sorted(
            [
                {
                    "serviceId": bucket["serviceId"],
                    "timetableCount": bucket["timetableCount"],
                    "entryCount": bucket["entryCount"],
                    "stopCount": len(bucket["stopIds"]),
                }
                for bucket in by_service.values()
            ],
            key=lambda item: item["serviceId"],
        ),
        "byStop": sorted(
            [
                {
                    "stopId": bucket["stopId"],
                    "stopName": bucket["stopName"],
                    "timetableCount": bucket["timetableCount"],
                    "entryCount": bucket["entryCount"],
                    "serviceCount": len(bucket["serviceIds"]),
                }
                for bucket in by_stop.values()
                if bucket["stopId"]
            ],
            key=lambda item: (item["stopName"], item["stopId"]),
        )[:200],
        "imports": imports,
    }


# ── Pydantic models ────────────────────────────────────────────


class CreateScenarioBody(BaseModel):
    name: str
    description: str = ""
    mode: str = "thesis_mode"
    operatorId: Literal["tokyu"] = "tokyu"
    datasetId: str = research_catalog.default_dataset_id()
    randomSeed: int = 42


class UpdateScenarioBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    operatorId: Optional[Literal["tokyu"]] = None


class DuplicateScenarioBody(BaseModel):
    name: Optional[str] = None


class UpdateDispatchScopeBody(BaseModel):
    scopeId: Optional[str] = None
    operatorId: Optional[str] = None
    datasetVersion: Optional[str] = None
    depotId: Optional[str] = None
    serviceId: Optional[str] = None
    depotSelection: Optional[Dict[str, Any]] = None
    routeSelection: Optional[Dict[str, Any]] = None
    serviceSelection: Optional[Dict[str, Any]] = None
    tripSelection: Optional[Dict[str, Any]] = None
    allowIntraDepotRouteSwap: Optional[bool] = None
    allowInterDepotSwap: Optional[bool] = None


class UpdateQuickSetupBody(BaseModel):
    selectedDepotIds: Optional[List[str]] = None
    selectedRouteIds: Optional[List[str]] = None
    dayType: Optional[str] = None
    serviceDate: Optional[str] = None
    includeShortTurn: Optional[bool] = None
    includeDepotMoves: Optional[bool] = None
    includeDeadhead: Optional[bool] = None
    allowIntraDepotRouteSwap: Optional[bool] = None
    allowInterDepotSwap: Optional[bool] = None
    solverMode: Optional[str] = None
    objectiveMode: Optional[str] = None
    timeLimitSeconds: Optional[int] = None
    mipGap: Optional[float] = None
    alnsIterations: Optional[int] = None
    allowPartialService: Optional[bool] = None
    unservedPenalty: Optional[float] = None
    gridFlatPricePerKwh: Optional[float] = None
    gridSellPricePerKwh: Optional[float] = None
    demandChargeCostPerKw: Optional[float] = None
    dieselPricePerL: Optional[float] = None
    gridCo2KgPerKwh: Optional[float] = None
    co2PricePerKg: Optional[float] = None
    iceCo2KgPerL: Optional[float] = None
    depotPowerLimitKw: Optional[float] = None
    degradationWeight: Optional[float] = None


class TimetableRowBody(BaseModel):
    route_id: str
    service_id: str = "WEEKDAY"
    direction: str = "outbound"
    canonicalDirection: Optional[str] = None
    routeVariantType: Optional[str] = None
    trip_index: int = 0
    origin: str
    destination: str
    origin_stop_id: Optional[str] = None
    destination_stop_id: Optional[str] = None
    departure: str  # HH:MM (24h, may exceed 24 for overnight)
    arrival: str  # HH:MM
    distance_km: float = 0.0
    allowed_vehicle_types: List[str] = ["BEV", "ICE"]


class UpdateTimetableBody(BaseModel):
    rows: List[TimetableRowBody]


class ImportCsvBody(BaseModel):
    content: str  # raw CSV text (UTF-8)


# ── Helpers ────────────────────────────────────────────────────


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


def _runtime_err_to_http(e: RuntimeError) -> HTTPException:
    """Convert a store RuntimeError into an HTTPException.

    RuntimeError with 'artifacts are incomplete' → 409 INCOMPLETE_ARTIFACT.
    Other RuntimeErrors → re-raise as-is (FastAPI will 500 them).
    """
    msg = str(e)
    if "artifacts are incomplete" in msg:
        return HTTPException(
            status_code=409,
            detail={"code": "INCOMPLETE_ARTIFACT", "message": msg},
        )
    raise e


def _ensure_runtime_master_data(scenario_id: str) -> None:
    try:
        store.ensure_runtime_master_data(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


def _scenario_dataset_id(doc: Dict[str, Any]) -> Optional[str]:
    meta = dict(doc.get("meta") or {})
    overlay = dict(doc.get("scenario_overlay") or {})
    feed_context = dict(doc.get("feed_context") or {})
    for value in (
        feed_context.get("datasetId"),
        overlay.get("dataset_id"),
        overlay.get("datasetId"),
        meta.get("datasetId"),
    ):
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return None


def _shard_scope_params(
    scenario_id: str,
    doc: Dict[str, Any],
    *,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    dataset_id = _scenario_dataset_id(doc)
    if not dataset_id or not shard_runtime_ready(dataset_id):
        return None
    dispatch_scope = store._normalize_dispatch_scope(doc)
    depot_ids = [str(item) for item in (dispatch_scope.get("depotSelection") or {}).get("depotIds") or [] if str(item or "").strip()]
    if depot_id and depot_id not in depot_ids:
        depot_ids.insert(0, depot_id)
    service_ids = [str(item) for item in (dispatch_scope.get("serviceSelection") or {}).get("serviceIds") or [] if str(item or "").strip()]
    if service_id and service_id not in service_ids:
        service_ids.insert(0, service_id)
    route_ids = list(store.effective_route_ids_for_scope(scenario_id, dispatch_scope))
    return {
        "dataset_id": dataset_id,
        "dispatch_scope": dispatch_scope,
        "depot_ids": depot_ids,
        "service_ids": service_ids,
        "route_ids": route_ids,
    }


def _load_shard_timetable_rows(
    scenario_id: str,
    doc: Dict[str, Any],
    *,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    scope_params = _shard_scope_params(
        scenario_id,
        doc,
        service_id=service_id,
        depot_id=depot_id,
    )
    if scope_params is None:
        return None
    return load_trip_rows_for_scope(
        dataset_id=scope_params["dataset_id"],
        route_ids=scope_params["route_ids"],
        depot_ids=scope_params["depot_ids"],
        service_ids=scope_params["service_ids"],
    )


def _pick_latest_scenario(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not items:
        return None
    return sorted(
        items,
        key=lambda x: (
            str(x.get("updatedAt", "")),
            str(x.get("createdAt", "")),
            str(x.get("id", "")),
        ),
        reverse=True,
    )[0]


def _scenario_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "description": item.get("description"),
        "mode": item.get("mode"),
        "operatorId": item.get("operatorId"),
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
        "status": item.get("status"),
        "datasetId": item.get("datasetId"),
        "datasetVersion": item.get("datasetVersion"),
        "randomSeed": item.get("randomSeed"),
    }


def _route_display_name(route: Dict[str, Any]) -> str:
    return str(
        route.get("routeFamilyLabel")
        or route.get("routeLabel")
        or route.get("routeCode")
        or route.get("name")
        or route.get("id")
        or ""
    )


def _route_trip_count(route: Dict[str, Any]) -> int:
    try:
        value = route.get("tripCount")
        if value in (None, ""):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _normalize_direction(value: Any, default: str = "outbound") -> str:
    return normalize_direction(value, default=default)


def _normalize_variant_type(value: Any) -> str:
    if str(value or "").strip() == "":
        return "unknown"
    return normalize_variant_type(value, direction="unknown")


def _depot_route_index(doc: Dict[str, Any]) -> Dict[str, List[str]]:
    route_ids_by_depot: Dict[str, List[str]] = {}
    route_lookup = {
        str(route.get("id") or ""): dict(route)
        for route in doc.get("routes") or []
        if route.get("id") is not None
    }
    for assignment in doc.get("route_depot_assignments") or []:
        depot_id = str(assignment.get("depotId") or "").strip()
        route_id = str(assignment.get("routeId") or "").strip()
        if not depot_id or not route_id or route_id not in route_lookup:
            continue
        route_ids_by_depot.setdefault(depot_id, [])
        if route_id not in route_ids_by_depot[depot_id]:
            route_ids_by_depot[depot_id].append(route_id)
    for route_id, route in route_lookup.items():
        depot_id = str(route.get("depotId") or "").strip()
        if not depot_id:
            continue
        route_ids_by_depot.setdefault(depot_id, [])
        if route_id not in route_ids_by_depot[depot_id]:
            route_ids_by_depot[depot_id].append(route_id)
    return {
        depot_id: sorted(route_ids)
        for depot_id, route_ids in route_ids_by_depot.items()
    }


def _depot_route_summary(
    doc: Dict[str, Any],
    route_index: Dict[str, List[str]],
    dispatch_scope: Dict[str, Any],
) -> List[Dict[str, Any]]:
    routes_by_id = {
        str(route.get("id") or ""): dict(route)
        for route in doc.get("routes") or []
        if route.get("id") is not None
    }
    selected_route_ids = set(dispatch_scope.get("effectiveRouteIds") or [])
    selected_depot_ids = set(
        (dispatch_scope.get("depotSelection") or {}).get("depotIds") or []
    )
    items: List[Dict[str, Any]] = []
    for depot in doc.get("depots") or []:
        depot_id = str(depot.get("id") or depot.get("depotId") or "").strip()
        if not depot_id:
            continue
        route_ids = route_index.get(depot_id) or []
        trip_count = sum(_route_trip_count(routes_by_id.get(route_id) or {}) for route_id in route_ids)
        items.append(
            {
                "depotId": depot_id,
                "name": depot.get("name") or depot_id,
                "routeCount": len(route_ids),
                "selected": depot_id in selected_depot_ids,
                "selectedRouteCount": len([route_id for route_id in route_ids if route_id in selected_route_ids]),
                "tripCount": trip_count,
            }
        )
    return items


def _available_day_types(doc: Dict[str, Any], dispatch_scope: Dict[str, Any]) -> List[Dict[str, Any]]:
    selected = str(dispatch_scope.get("serviceId") or "").strip()
    items: List[Dict[str, Any]] = []
    for entry in doc.get("calendar") or []:
        service_id = canonical_service_id(entry.get("service_id"))
        label = str(entry.get("name") or service_id)
        if any(item.get("serviceId") == service_id for item in items):
            continue
        items.append(
            {
                "serviceId": service_id,
                "label": label,
                "isDefault": service_id == selected,
            }
        )
    if not items:
        items.append({"serviceId": "WEEKDAY", "label": "平日", "isDefault": True})
    return items


def _quick_setup_candidate_route_ids(
    doc: Dict[str, Any],
    route_index: Dict[str, List[str]],
    *,
    selected_depot_ids: List[str],
) -> List[str]:
    if selected_depot_ids:
        route_ids: List[str] = []
        for depot_id in selected_depot_ids:
            for route_id in route_index.get(depot_id) or []:
                normalized = str(route_id).strip()
                if normalized and normalized not in route_ids:
                    route_ids.append(normalized)
        return route_ids
    return [
        str(route.get("id") or "").strip()
        for route in doc.get("routes") or []
        if str(route.get("id") or "").strip()
    ]


def _route_trip_inventory_for_quick_setup(
    doc: Dict[str, Any],
    dispatch_scope: Dict[str, Any],
    route_index: Dict[str, List[str]],
    *,
    selected_depot_ids: List[str],
) -> Tuple[Dict[str, Dict[str, int]], List[Dict[str, Any]]]:
    available_day_types = _available_day_types(doc, dispatch_scope)
    default_day_type_summaries = [
        {
            "serviceId": canonical_service_id(item.get("serviceId")),
            "label": str(item.get("label") or item.get("serviceId") or ""),
            "routeCount": 0,
            "tripCount": 0,
            "selected": bool(item.get("isDefault")),
        }
        for item in available_day_types
    ]

    candidate_route_ids = _quick_setup_candidate_route_ids(
        doc,
        route_index,
        selected_depot_ids=selected_depot_ids,
    )
    candidate_route_set = set(candidate_route_ids) if candidate_route_ids else None

    summary: Optional[Dict[str, Any]] = None
    dataset_id = _scenario_dataset_id(doc)
    if dataset_id and shard_runtime_ready(dataset_id):
        summary = build_timetable_summary_for_scope(
            dataset_id=dataset_id,
            route_ids=candidate_route_ids,
            depot_ids=selected_depot_ids or None,
            service_ids=None,
        )

    if not summary:
        return {}, default_day_type_summaries

    route_counts_by_day_type: Dict[str, Dict[str, int]] = {}
    for raw_service_id, raw_route_counts in (summary.get("routeServiceCounts") or {}).items():
        service_id = canonical_service_id(raw_service_id)
        if not isinstance(raw_route_counts, dict):
            continue
        for route_id, raw_count in raw_route_counts.items():
            normalized_route_id = str(route_id or "").strip()
            if not normalized_route_id:
                continue
            try:
                count = int(raw_count or 0)
            except (TypeError, ValueError):
                count = 0
            if count <= 0:
                continue
            bucket = route_counts_by_day_type.setdefault(normalized_route_id, {})
            bucket[service_id] = bucket.get(service_id, 0) + count

    label_by_service_id = {
        canonical_service_id(item.get("serviceId")): str(item.get("label") or item.get("serviceId") or "")
        for item in available_day_types
    }
    summary_by_service_id: Dict[str, Dict[str, Any]] = {}
    for entry in summary.get("byService") or []:
        service_id = canonical_service_id(entry.get("serviceId"))
        summary_by_service_id[service_id] = dict(entry)
    ordered_service_ids: List[str] = []
    for service_id in label_by_service_id.keys():
        if service_id not in ordered_service_ids:
            ordered_service_ids.append(service_id)
    for service_id in summary_by_service_id.keys():
        if service_id not in ordered_service_ids:
            ordered_service_ids.append(service_id)

    selected_service_id = canonical_service_id(dispatch_scope.get("serviceId"))
    day_type_summaries: List[Dict[str, Any]] = []
    for service_id in ordered_service_ids:
        bucket = summary_by_service_id.get(service_id) or {}
        day_type_summaries.append(
            {
                "serviceId": service_id,
                "label": label_by_service_id.get(service_id) or service_id,
                "routeCount": int(bucket.get("routeCount") or 0),
                "tripCount": int(bucket.get("rowCount") or 0),
                "selected": service_id == selected_service_id,
            }
        )

    return route_counts_by_day_type, day_type_summaries


def _builder_defaults(
    doc: Dict[str, Any],
    route_index: Dict[str, List[str]],
    dispatch_scope: Dict[str, Any],
) -> Dict[str, Any]:
    overlay = dict(doc.get("scenario_overlay") or {})
    simulation_config = dict(doc.get("simulation_config") or {})
    template_items = [dict(item) for item in doc.get("vehicle_templates") or []]
    primary_depot_id = str(dispatch_scope.get("depotId") or "").strip()
    selected_depot_ids = list((dispatch_scope.get("depotSelection") or {}).get("depotIds") or [])
    if not selected_depot_ids and primary_depot_id:
        selected_depot_ids = [primary_depot_id]
    if not selected_depot_ids and doc.get("depots"):
        selected_depot_ids = [str((doc.get("depots") or [])[0].get("id") or "")]
    if not primary_depot_id and selected_depot_ids:
        primary_depot_id = selected_depot_ids[0]

    selected_route_ids = list(dispatch_scope.get("effectiveRouteIds") or [])
    if not selected_route_ids and primary_depot_id:
        selected_route_ids = list(route_index.get(primary_depot_id) or [])

    primary_template = next(
        (
            template
            for template in template_items
            if str(template.get("type") or "").upper() == "BEV"
        ),
        template_items[0] if template_items else {},
    )
    existing_vehicles = [
        dict(item)
        for item in doc.get("vehicles") or []
        if not primary_depot_id or str(item.get("depotId") or "") == primary_depot_id
    ]
    existing_chargers = [
        dict(item)
        for item in doc.get("chargers") or []
        if not primary_depot_id
        or str(item.get("siteId") or item.get("site_id") or "") == primary_depot_id
    ]
    overlay_fleet = dict(overlay.get("fleet") or {})
    overlay_cost = dict(overlay.get("cost_coefficients") or {})
    overlay_charging = dict(overlay.get("charging_constraints") or {})
    overlay_solver = dict(overlay.get("solver_config") or {})
    grouped_fleet_templates: Dict[str, Dict[str, Any]] = {}
    for vehicle in existing_vehicles:
        template_id = str(vehicle.get("vehicleTemplateId") or "")
        if not template_id:
            continue
        group = grouped_fleet_templates.setdefault(
            template_id,
            {
                "vehicleTemplateId": template_id,
                "vehicleCount": 0,
                "initialSoc": vehicle.get("initialSoc"),
                "batteryKwh": vehicle.get("batteryKwh"),
                "chargePowerKw": vehicle.get("chargePowerKw"),
            },
        )
        group["vehicleCount"] += 1
    fleet_templates = list(grouped_fleet_templates.values())

    return {
        "selectedDepotIds": selected_depot_ids,
        "selectedRouteIds": selected_route_ids,
        "dayType": str(dispatch_scope.get("serviceId") or "WEEKDAY"),
        "serviceDate": simulation_config.get("service_date"),
        "vehicleTemplateId": primary_template.get("id"),
        "vehicleCount": len(existing_vehicles) or int(overlay_fleet.get("n_bev") or 10),
        "initialSoc": simulation_config.get("initial_soc", 0.8),
        "batteryKwh": (
            existing_vehicles[0].get("batteryKwh")
            if existing_vehicles
            else primary_template.get("batteryKwh")
        ),
        "chargerCount": len(existing_chargers) or int(overlay_charging.get("max_simultaneous_sessions") or 4),
        "chargerPowerKw": (
            existing_chargers[0].get("powerKw")
            if existing_chargers
            else overlay_charging.get("charger_power_limit_kw")
            or primary_template.get("chargePowerKw")
            or 90
        ),
        "solverMode": overlay_solver.get("mode") or "mode_milp_only",
        "objectiveMode": normalize_objective_mode(
            overlay_solver.get("objective_mode")
            or simulation_config.get("objective_mode")
            or "total_cost"
        ),
        "allowPartialService": bool(
            overlay_solver.get(
                "allow_partial_service",
                simulation_config.get("allow_partial_service", False),
            )
        ),
        "unservedPenalty": float(
            overlay_solver.get(
                "unserved_penalty",
                simulation_config.get("unserved_penalty", 10000.0),
            )
        ),
        "gridFlatPricePerKwh": overlay_cost.get("grid_flat_price_per_kwh"),
        "gridSellPricePerKwh": overlay_cost.get("grid_sell_price_per_kwh"),
        "demandChargeCostPerKw": overlay_cost.get("demand_charge_cost_per_kw"),
        "dieselPricePerL": overlay_cost.get("diesel_price_per_l"),
        "gridCo2KgPerKwh": overlay_cost.get("grid_co2_kg_per_kwh"),
        "co2PricePerKg": overlay_cost.get("co2_price_per_kg"),
        "iceCo2KgPerL": overlay_cost.get("ice_co2_kg_per_l"),
        "depotPowerLimitKw": overlay_charging.get("depot_power_limit_kw"),
        "degradationWeight": (
            (overlay_solver.get("objective_weights") or {}).get("degradation")
            or (overlay_solver.get("objective_weights") or {}).get("battery_degradation_cost")
        ),
        "touPricing": list(overlay_cost.get("tou_pricing") or []),
        "fleetTemplates": fleet_templates,
        "timeLimitSeconds": int(overlay_solver.get("time_limit_seconds") or 300),
        "mipGap": float(overlay_solver.get("mip_gap") or 0.01),
        "alnsIterations": int(
            overlay_solver.get("alns_iterations")
            or simulation_config.get("alns_iterations")
            or 500
        ),
        "randomSeed": next(
            (
                value
                for value in (
                    simulation_config.get("random_seed"),
                    overlay.get("random_seed"),
                    (doc.get("meta") or {}).get("randomSeed"),
                    42,
                )
                if value is not None
            ),
            42,
        ),
        "experimentMethod": simulation_config.get("experiment_method"),
        "experimentNotes": simulation_config.get("experiment_notes"),
        "includeDeadhead": bool(
            (dispatch_scope.get("tripSelection") or {}).get("includeDeadhead", True)
        ),
        "startTime": simulation_config.get("start_time") or "05:00",
        "planningHorizonHours": float(
            simulation_config.get("planning_horizon_hours") or 20.0
        ),
    }


def _quick_setup_route_selection_patch(
    doc: Dict[str, Any],
    current_scope: Dict[str, Any],
    *,
    selected_depot_ids: List[str],
    selected_route_ids: List[str],
) -> Dict[str, Any]:
    route_selection = {
        **dict(current_scope.get("routeSelection") or {}),
        "mode": "refine",
        "includeRouteFamilyCodes": [],
        "excludeRouteFamilyCodes": [],
    }
    route_index = _depot_route_index(doc)
    candidate_route_ids: List[str] = []
    for depot_id in selected_depot_ids:
        for route_id in route_index.get(depot_id) or []:
            if route_id not in candidate_route_ids:
                candidate_route_ids.append(route_id)

    selected_route_set = set(selected_route_ids)
    candidate_route_set = set(candidate_route_ids)
    route_selection["includeRouteIds"] = [
        route_id
        for route_id in selected_route_ids
        if route_id not in candidate_route_set
    ]
    route_selection["excludeRouteIds"] = [
        route_id
        for route_id in candidate_route_ids
        if route_id not in selected_route_set
    ]
    return route_selection


def _quick_route_items(
    doc: Dict[str, Any],
    selected_depot_ids: List[str],
    selected_route_ids: List[str],
    *,
    selected_day_type: str,
    route_trip_counts_by_day_type: Dict[str, Dict[str, int]],
    route_limit: int,
) -> List[Dict[str, Any]]:
    selected_depot_set = {
        str(item).strip() for item in selected_depot_ids if str(item).strip()
    }
    selected_route_set = {
        str(item).strip() for item in selected_route_ids if str(item).strip()
    }

    routes = [dict(route) for route in doc.get("routes") or []]
    # Build effective depot index (covers route_depot_assignments AND route.depotId)
    route_index = _depot_route_index(doc)
    # Reverse index: route_id -> effective depot_id
    effective_depot_by_route: Dict[str, str] = {}
    for depot_id, rids in route_index.items():
        for rid in rids:
            if rid not in effective_depot_by_route:
                effective_depot_by_route[rid] = depot_id

    if selected_depot_set:
        scoped_route_ids = {
            route_id
            for depot_id in selected_depot_set
            for route_id in (route_index.get(depot_id) or [])
        }
        routes = [
            route
            for route in routes
            if str(route.get("id") or "").strip() in scoped_route_ids
        ]

    routes.sort(
        key=lambda route: (
            # Group by effective depot first so routes cluster correctly
            effective_depot_by_route.get(str(route.get("id") or "").strip(), ""),
            str(
                route.get("routeFamilyCode")
                or route.get("routeCode")
                or route.get("name")
                or ""
            ),
            int(route.get("familySortOrder") or 999),
            str(route.get("routeLabel") or route.get("name") or ""),
            str(route.get("id") or ""),
        )
    )

    items: List[Dict[str, Any]] = []
    normalized_day_type = canonical_service_id(selected_day_type)
    filtered_routes: List[Dict[str, Any]] = []
    for route in routes:
        route_id = str(route.get("id") or "").strip()
        if not route_id:
            continue
        trip_counts_by_day_type = dict(route_trip_counts_by_day_type.get(route_id) or {})
        trip_count_total = (
            sum(int(value or 0) for value in trip_counts_by_day_type.values())
            if trip_counts_by_day_type
            else _route_trip_count(route)
        )
        trip_count_selected_day = int(
            trip_counts_by_day_type.get(normalized_day_type, trip_count_total if not trip_counts_by_day_type else 0)
        )
        if trip_counts_by_day_type and trip_count_selected_day <= 0:
            continue
        # Use effective depot (from assignments) if route.depotId is absent
        effective_depot_id = (
            effective_depot_by_route.get(route_id)
            or route.get("depotId")
        )
        filtered_routes.append(
            {
                "id": route_id,
                "displayName": _route_display_name(route),
                "routeCode": route.get("routeCode"),
                "routeLabel": route.get("routeLabel"),
                "routeFamilyCode": route.get("routeFamilyCode"),
                "routeFamilyLabel": route.get("routeFamilyLabel"),
                "routeSeriesCode": route.get("routeSeriesCode"),
                "depotId": effective_depot_id,
                "tripCount": trip_count_selected_day,
                "tripCountSelectedDay": trip_count_selected_day,
                "tripCountTotal": trip_count_total,
                "tripCountsByDayType": trip_counts_by_day_type,
                "familySortOrder": route.get("familySortOrder"),
                "routeVariantId": route.get("routeVariantId"),
                "isPrimaryVariant": route.get("isPrimaryVariant"),
                "routeVariantType": _normalize_variant_type(
                    route.get("routeVariantTypeManual")
                    or route.get("routeVariantType")
                ),
                "canonicalDirection": _normalize_direction(
                    route.get("canonicalDirectionManual")
                    or route.get("canonicalDirection")
                    or "outbound"
                ),
                "selected": route_id in selected_route_set,
            }
        )
    return filtered_routes[: max(1, route_limit)]


def _build_quick_setup_payload(
    scenario: Dict[str, Any],
    doc: Dict[str, Any],
    dispatch_scope: Dict[str, Any],
    *,
    selected_depot_ids: List[str],
    route_limit: int,
) -> Dict[str, Any]:
    route_index = _depot_route_index(doc)
    builder_defaults = _builder_defaults(doc, route_index, dispatch_scope)
    selected_day_type = canonical_service_id(dispatch_scope.get("serviceId"))
    selected_route_ids = [
        str(route_id).strip()
        for route_id in list(dispatch_scope.get("effectiveRouteIds") or [])
        if str(route_id).strip()
    ]
    route_trip_counts_by_day_type, day_type_summaries = _route_trip_inventory_for_quick_setup(
        doc,
        dispatch_scope,
        route_index,
        selected_depot_ids=selected_depot_ids,
    )
    vehicles = [dict(item) for item in doc.get("vehicles") or []]
    vehicle_count_by_depot: Dict[str, int] = {}
    for vehicle in vehicles:
        depot_id = str(vehicle.get("depotId") or "").strip()
        if not depot_id:
            continue
        vehicle_count_by_depot[depot_id] = vehicle_count_by_depot.get(depot_id, 0) + 1

    depots: List[Dict[str, Any]] = []
    selected_depot_set = {
        str(item).strip() for item in selected_depot_ids if str(item).strip()
    }
    for depot in doc.get("depots") or []:
        depot_id = str(depot.get("id") or "").strip()
        if not depot_id:
            continue
        depots.append(
            {
                "id": depot_id,
                "name": depot.get("name") or depot_id,
                "location": depot.get("location") or "",
                "routeCount": len(route_index.get(depot_id) or []),
                "vehicleCount": vehicle_count_by_depot.get(depot_id, 0),
                "selected": depot_id in selected_depot_set,
            }
        )

    return {
        "scenario": {
            "id": scenario.get("id"),
            "name": scenario.get("name"),
            "operatorId": scenario.get("operatorId"),
            "datasetVersion": scenario.get("datasetVersion"),
            "status": scenario.get("status"),
            "feedContext": scenario.get("feedContext"),
            "stats": scenario.get("stats"),
        },
        "selectedDepotIds": selected_depot_ids,
        "selectedRouteIds": selected_route_ids,
        "depots": depots,
        "routes": _quick_route_items(
            doc,
            selected_depot_ids,
            selected_route_ids,
            selected_day_type=selected_day_type,
            route_trip_counts_by_day_type=route_trip_counts_by_day_type,
            route_limit=route_limit,
        ),
        "dispatchScope": {
            "dayType": selected_day_type,
            "routeSelectionMode": str(
                ((dispatch_scope.get("routeSelection") or {}).get("mode") or "include")
            ),
            "tripSelection": dict(dispatch_scope.get("tripSelection") or {}),
            "allowIntraDepotRouteSwap": bool(
                dispatch_scope.get("allowIntraDepotRouteSwap", False)
            ),
            "allowInterDepotSwap": bool(
                dispatch_scope.get("allowInterDepotSwap", False)
            ),
        },
        "availableDayTypes": _available_day_types(doc, dispatch_scope),
        "dayTypeSummaries": day_type_summaries,
        "solverSettings": {
            "solverMode": builder_defaults.get("solverMode") or "mode_milp_only",
            "objectiveMode": normalize_objective_mode(
                builder_defaults.get("objectiveMode") or "total_cost"
            ),
            "timeLimitSeconds": int(builder_defaults.get("timeLimitSeconds") or 300),
            "mipGap": float(builder_defaults.get("mipGap") or 0.01),
            "alnsIterations": int(builder_defaults.get("alnsIterations") or 500),
        },
        "simulationSettings": {
            "serviceDate": builder_defaults.get("serviceDate"),
            "vehicleTemplateId": builder_defaults.get("vehicleTemplateId"),
            "vehicleCount": int(builder_defaults.get("vehicleCount") or 0),
            "chargerCount": int(builder_defaults.get("chargerCount") or 0),
            "chargerPowerKw": float(builder_defaults.get("chargerPowerKw") or 0.0),
            "includeDeadhead": bool(builder_defaults.get("includeDeadhead", True)),
            "gridFlatPricePerKwh": builder_defaults.get("gridFlatPricePerKwh"),
            "gridSellPricePerKwh": builder_defaults.get("gridSellPricePerKwh"),
            "demandChargeCostPerKw": builder_defaults.get("demandChargeCostPerKw"),
            "dieselPricePerL": builder_defaults.get("dieselPricePerL"),
            "gridCo2KgPerKwh": builder_defaults.get("gridCo2KgPerKwh"),
            "co2PricePerKg": builder_defaults.get("co2PricePerKg"),
            "iceCo2KgPerL": builder_defaults.get("iceCo2KgPerL"),
            "depotPowerLimitKw": builder_defaults.get("depotPowerLimitKw"),
            "degradationWeight": builder_defaults.get("degradationWeight"),
            "allowPartialService": bool(builder_defaults.get("allowPartialService", False)),
            "unservedPenalty": float(builder_defaults.get("unservedPenalty") or 10000.0),
        },
    }


def _build_editor_bootstrap_payload(
    doc: Dict[str, Any],
    scenario: Dict[str, Any],
    *,
    include_routes: bool,
    include_builder: bool,
) -> Dict[str, Any]:
    dispatch_scope = store._normalize_dispatch_scope(doc)
    route_index = _depot_route_index(doc)

    # Routes: return only the fields required by the SimulationBuilder and
    # route-family grouping logic. Heavy fields are omitted.
    _ROUTE_SLIM_KEYS = {
        "id", "name", "routeCode", "routeLabel", "startStop", "endStop",
        "distanceKm", "durationMin", "color", "enabled", "source",
        "depotId", "assignmentType", "tripCount", "linkState",
        "routeFamilyId", "routeFamilyCode", "routeFamilyLabel",
        "routeVariantId", "routeVariantType", "canonicalDirection",
        "isPrimaryVariant", "familySortOrder", "classificationConfidence",
        "patternId", "busrouteId",
    }

    def _slim_route(route: dict) -> dict:
        slimmed = {k: v for k, v in dict(route).items() if k in _ROUTE_SLIM_KEYS}
        slimmed["displayName"] = _route_display_name(route)
        return slimmed

    dataset_status = scenario.get("datasetStatus")
    if isinstance(dataset_status, dict):
        dataset_status = {
            k: v
            for k, v in dataset_status.items()
            if k not in ("shardManifest", "manifest", "paths")
        }

    if include_routes:
        overlay_key = "scenario" + "Overlay"
        slim_scenario = {
            k: v
            for k, v in scenario.items()
            if k not in ("datasetStatus", "refs", "stats", overlay_key)
        }
    else:
        # lite payload keeps stats so the planning header can avoid extra summary queries.
        overlay_key = "scenario" + "Overlay"
        slim_scenario = {
            k: v
            for k, v in scenario.items()
            if k not in ("datasetStatus", "refs", overlay_key)
        }

    payload: Dict[str, Any] = {
        "scenario": slim_scenario,
        "dispatchScope": dispatch_scope,
        "depots": [dict(item) for item in doc.get("depots") or []],
        "depotRouteSummary": _depot_route_summary(doc, route_index, dispatch_scope),
        "datasetVersion": scenario.get("datasetVersion"),
        "datasetStatus": dataset_status,
        "warning": (scenario.get("datasetStatus") or {}).get("warning"),
    }

    if include_routes:
        payload["routes"] = [_slim_route(r) for r in doc.get("routes") or []]
        payload["vehicleTemplates"] = [dict(item) for item in doc.get("vehicle_templates") or []]
        payload["depotRouteIndex"] = route_index

    if include_builder:
        payload["availableDayTypes"] = _available_day_types(doc, dispatch_scope)
        payload["builderDefaults"] = _builder_defaults(doc, route_index, dispatch_scope)

    return payload


def _has_materialized_bootstrap(doc: Dict[str, Any]) -> bool:
    return bool(doc.get("depots")) and bool(doc.get("routes")) and bool(
        doc.get("vehicle_templates")
    )


def _ensure_scenario_bootstrap_persisted(scenario_id: str) -> Dict[str, Any]:
    scenario_doc = store.get_scenario_document(
        scenario_id,
        repair_missing_master=False,
    )
    has_core_setup = _has_materialized_bootstrap(scenario_doc)
    if has_core_setup:
        return store.get_scenario(scenario_id)

    meta = dict(scenario_doc.get("meta") or {})
    overlay = dict(scenario_doc.get("scenario_overlay") or {})
    feed_context = dict(scenario_doc.get("feed_context") or {})
    dataset_id = str(
        overlay.get("dataset_id")
        or overlay.get("datasetId")
        or feed_context.get("datasetId")
        or meta.get("datasetId")
        or research_catalog.default_dataset_id()
    )
    random_seed = int(
        overlay.get("random_seed")
        or overlay.get("randomSeed")
        or meta.get("randomSeed")
        or 42
    )
    bootstrap = research_catalog.bootstrap_scenario(
        scenario_id=scenario_id,
        dataset_id=dataset_id,
        random_seed=random_seed,
    )
    return store.apply_dataset_bootstrap(scenario_id, bootstrap)


# ── Scenario CRUD ──────────────────────────────────────────────


@router.get("/scenarios")
def list_scenarios() -> Dict[str, Any]:
    items = [_scenario_summary(item) for item in store.list_scenarios()]
    return {"items": items, "total": len(items)}


@router.get("/scenarios/default")
def get_or_create_default_scenario() -> Dict[str, Any]:
    """
    Legacy helper retained for compatibility.
    Returns the latest scenario metadata if one exists.
    """
    with _default_scenario_lock:
        items = store.list_scenarios()
        latest = _pick_latest_scenario(items)
        if latest is None:
            raise HTTPException(status_code=404, detail="No scenarios found")
        return _scenario_summary(latest)


@router.post("/scenarios", status_code=201)
def create_scenario(body: CreateScenarioBody) -> Dict[str, Any]:
    meta = store.create_scenario(
        name=body.name,
        description=body.description,
        mode=body.mode,
        operator_id=body.operatorId,
    )
    try:
        bootstrap = research_catalog.bootstrap_scenario(
            scenario_id=meta["id"],
            dataset_id=body.datasetId,
            random_seed=body.randomSeed,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Dataset '{body.datasetId}' not found")
    return store.apply_dataset_bootstrap(meta["id"], bootstrap)


@router.post("/scenarios/{scenario_id}/duplicate", status_code=201)
def duplicate_scenario(
    scenario_id: str, body: Optional[DuplicateScenarioBody] = None
) -> Dict[str, Any]:
    try:
        return store.duplicate_scenario(scenario_id, name=body.name if body else None)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str) -> Dict[str, Any]:
    try:
        return store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        if "artifacts are incomplete" in str(e):
            raise HTTPException(
                status_code=409,
                detail={"code": "INCOMPLETE_ARTIFACT", "message": str(e)},
            )
        raise


@router.get("/scenarios/{scenario_id}/editor-bootstrap")
def get_editor_bootstrap(scenario_id: str) -> Dict[str, Any]:
    _ensure_runtime_master_data(scenario_id)
    try:
        # Use shallow load: skips timetable_rows, trips, graph, duties etc.
        # Only meta + master data (depots, vehicles, routes, …) is loaded.
        doc = store.get_scenario_document_shallow(scenario_id)
        scenario = store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)

    return _build_editor_bootstrap_payload(
        doc,
        scenario,
        include_routes=True,
        include_builder=True,
    )


@router.get("/scenarios/{scenario_id}/editor-bootstrap-lite")
def get_editor_bootstrap_lite(scenario_id: str) -> Dict[str, Any]:
    _ensure_runtime_master_data(scenario_id)
    try:
        doc = store.get_scenario_document_shallow(scenario_id)
        scenario = store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)

    return _build_editor_bootstrap_payload(
        doc,
        scenario,
        include_routes=False,
        include_builder=False,
    )


@router.get("/scenarios/{scenario_id}/quick-setup")
def get_quick_setup(
    scenario_id: str,
    depot_ids: Optional[str] = Query(default=None, alias="depotIds"),
    route_limit: int = Query(default=300, ge=50, le=1000, alias="routeLimit"),
) -> Dict[str, Any]:
    _ensure_runtime_master_data(scenario_id)
    try:
        doc = store.get_scenario_document_shallow(scenario_id)
        scenario = store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)

    dispatch_scope = store._normalize_dispatch_scope(doc)
    selected_depot_ids = [
        str(item).strip()
        for item in (dispatch_scope.get("depotSelection") or {}).get("depotIds") or []
        if str(item).strip()
    ]
    if depot_ids:
        parsed_depots = [
            item.strip()
            for item in depot_ids.split(",")
            if isinstance(item, str) and item.strip()
        ]
        if parsed_depots:
            selected_depot_ids = parsed_depots

    return _build_quick_setup_payload(
        scenario,
        doc,
        dispatch_scope,
        selected_depot_ids=selected_depot_ids,
        route_limit=route_limit,
    )


@router.put("/scenarios/{scenario_id}/quick-setup")
def update_quick_setup(scenario_id: str, body: UpdateQuickSetupBody) -> Dict[str, Any]:
    _ensure_runtime_master_data(scenario_id)
    try:
        current_scope = store.get_dispatch_scope(scenario_id)
        doc = store.get_scenario_document_shallow(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)

    selected_depot_ids = [
        str(item).strip() for item in (body.selectedDepotIds or []) if str(item).strip()
    ]
    selected_route_ids = [
        str(item).strip() for item in (body.selectedRouteIds or []) if str(item).strip()
    ]
    day_type = str(body.dayType or current_scope.get("serviceId") or "WEEKDAY")

    patch: Dict[str, Any] = {
        "serviceId": day_type,
        "serviceSelection": {"serviceIds": [day_type]},
        "depotSelection": {
            **dict(current_scope.get("depotSelection") or {}),
            "mode": "include",
            "depotIds": selected_depot_ids,
            "primaryDepotId": selected_depot_ids[0] if selected_depot_ids else None,
        },
        "routeSelection": _quick_setup_route_selection_patch(
            doc,
            current_scope,
            selected_depot_ids=selected_depot_ids,
            selected_route_ids=selected_route_ids,
        ),
    }
    if selected_depot_ids:
        patch["depotId"] = selected_depot_ids[0]
    if body.includeShortTurn is not None or body.includeDepotMoves is not None or body.includeDeadhead is not None:
        patch["tripSelection"] = {
            **dict(current_scope.get("tripSelection") or {}),
            **(
                {"includeShortTurn": bool(body.includeShortTurn)}
                if body.includeShortTurn is not None
                else {}
            ),
            **(
                {"includeDepotMoves": bool(body.includeDepotMoves)}
                if body.includeDepotMoves is not None
                else {}
            ),
            **(
                {"includeDeadhead": bool(body.includeDeadhead)}
                if body.includeDeadhead is not None
                else {}
            ),
        }
    if body.allowIntraDepotRouteSwap is not None:
        patch["allowIntraDepotRouteSwap"] = bool(body.allowIntraDepotRouteSwap)
    if body.allowInterDepotSwap is not None:
        patch["allowInterDepotSwap"] = bool(body.allowInterDepotSwap)

    try:
        normalized_scope = store.set_dispatch_scope(scenario_id, patch)

        overlay = store.get_scenario_overlay(scenario_id) or {}
        solver_config = dict(overlay.get("solver_config") or {})
        if body.solverMode is not None:
            solver_config["mode"] = body.solverMode
        if body.objectiveMode is not None:
            solver_config["objective_mode"] = normalize_objective_mode(body.objectiveMode)
        if body.timeLimitSeconds is not None:
            solver_config["time_limit_seconds"] = int(body.timeLimitSeconds)
        if body.mipGap is not None:
            solver_config["mip_gap"] = float(body.mipGap)
        if body.alnsIterations is not None:
            solver_config["alns_iterations"] = int(body.alnsIterations)
        if body.allowPartialService is not None:
            solver_config["allow_partial_service"] = bool(body.allowPartialService)
        if body.unservedPenalty is not None:
            solver_config["unserved_penalty"] = float(body.unservedPenalty)
        current_objective_mode = normalize_objective_mode(
            solver_config.get("objective_mode") or "total_cost"
        )
        current_unserved_penalty = float(
            solver_config.get("unserved_penalty") or 10000.0
        )
        saved_weights = dict(solver_config.get("objective_weights") or {})

        overlay_cost = dict(overlay.get("cost_coefficients") or {})
        if body.gridFlatPricePerKwh is not None:
            overlay_cost["grid_flat_price_per_kwh"] = float(body.gridFlatPricePerKwh)
        if body.gridSellPricePerKwh is not None:
            overlay_cost["grid_sell_price_per_kwh"] = float(body.gridSellPricePerKwh)
        if body.demandChargeCostPerKw is not None:
            overlay_cost["demand_charge_cost_per_kw"] = float(body.demandChargeCostPerKw)
        if body.dieselPricePerL is not None:
            overlay_cost["diesel_price_per_l"] = float(body.dieselPricePerL)
        if body.gridCo2KgPerKwh is not None:
            overlay_cost["grid_co2_kg_per_kwh"] = float(body.gridCo2KgPerKwh)
        if body.co2PricePerKg is not None:
            overlay_cost["co2_price_per_kg"] = float(body.co2PricePerKg)
        if body.iceCo2KgPerL is not None:
            overlay_cost["ice_co2_kg_per_l"] = float(body.iceCo2KgPerL)

        if body.degradationWeight is not None:
            saved_weights["degradation"] = float(body.degradationWeight)
        if solver_config:
            solver_config["objective_weights"] = legacy_objective_weights_for_mode(
                objective_mode=current_objective_mode,
                unserved_penalty=current_unserved_penalty,
                explicit_weights=saved_weights,
            )

        overlay_charging = dict(overlay.get("charging_constraints") or {})
        if body.depotPowerLimitKw is not None:
            overlay_charging["depot_power_limit_kw"] = float(body.depotPowerLimitKw)

        if solver_config:
            overlay["solver_config"] = solver_config
        if overlay_cost:
            overlay["cost_coefficients"] = overlay_cost
        if overlay_charging:
            overlay["charging_constraints"] = overlay_charging
        if solver_config or overlay_cost or overlay_charging:
            store.set_scenario_overlay(scenario_id, overlay)

        simulation_config = store.get_field(scenario_id, "simulation_config") or {}
        if not isinstance(simulation_config, dict):
            simulation_config = {}
        if body.serviceDate is not None:
            simulation_config["service_date"] = body.serviceDate
        if body.objectiveMode is not None:
            simulation_config["objective_mode"] = normalize_objective_mode(body.objectiveMode)
        if body.timeLimitSeconds is not None:
            simulation_config["time_limit_seconds"] = int(body.timeLimitSeconds)
        if body.mipGap is not None:
            simulation_config["mip_gap"] = float(body.mipGap)
        if body.alnsIterations is not None:
            simulation_config["alns_iterations"] = int(body.alnsIterations)
        if body.allowPartialService is not None:
            simulation_config["allow_partial_service"] = bool(body.allowPartialService)
        if body.unservedPenalty is not None:
            simulation_config["unserved_penalty"] = float(body.unservedPenalty)
        if simulation_config:
            store.set_field(scenario_id, "simulation_config", simulation_config)

        doc = store.get_scenario_document_shallow(scenario_id)
        scenario = store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)

    selected_depot_ids_payload = [
        str(item).strip()
        for item in (normalized_scope.get("depotSelection") or {}).get("depotIds") or []
        if str(item).strip()
    ]
    return _build_quick_setup_payload(
        scenario,
        doc,
        normalized_scope,
        selected_depot_ids=selected_depot_ids_payload,
        route_limit=300,
    )


@router.put("/scenarios/{scenario_id}")
def update_scenario(scenario_id: str, body: UpdateScenarioBody) -> Dict[str, Any]:
    try:
        return store.update_scenario(
            scenario_id,
            name=body.name,
            description=body.description,
            mode=body.mode,
            operator_id=body.operatorId,
        )
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


@router.get("/scenarios/{scenario_id}/dispatch-scope")
def get_dispatch_scope(scenario_id: str) -> Dict[str, Any]:
    try:
        return store.get_dispatch_scope(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


@router.put("/scenarios/{scenario_id}/dispatch-scope")
def update_dispatch_scope(
    scenario_id: str, body: UpdateDispatchScopeBody
) -> Dict[str, Any]:
    try:
        return store.set_dispatch_scope(
            scenario_id,
            body.model_dump(exclude_unset=True),
        )
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


@router.get("/planning/depot-scope/{depot_id}/trips")
def get_depot_scope_trips(
    depot_id: str,
    scenario_id: str = Query(..., alias="scenarioId"),
    service_id: Optional[str] = Query(default=None, alias="serviceId"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    try:
        current_scope = store.get_dispatch_scope(scenario_id)
        scoped_scope = {
            **current_scope,
            "depotId": depot_id,
            "depotSelection": {
                **dict(current_scope.get("depotSelection") or {}),
                "mode": "include",
                "depotIds": [depot_id],
                "primaryDepotId": depot_id,
            },
        }
        if service_id:
            scoped_scope["serviceId"] = service_id
            scoped_scope["serviceSelection"] = {"serviceIds": [service_id]}
        route_ids = set(store.effective_route_ids_for_scope(scenario_id, scoped_scope))
        rows = list(store.get_field(scenario_id, "timetable_rows") or [])
        if not rows:
            doc = store.get_scenario_document(scenario_id)
            shard_rows = _load_shard_timetable_rows(
                scenario_id,
                doc,
                service_id=service_id,
                depot_id=depot_id,
            )
            if shard_rows is not None:
                rows = list(shard_rows)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)

    filtered = [
        row
        for row in rows
        if (not route_ids or str(row.get("route_id") or "") in route_ids)
        and (not service_id or str(row.get("service_id") or "") == service_id)
    ]
    paged = filtered[offset : offset + limit]
    return {
        "items": paged,
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "meta": {
            "depotId": depot_id,
            "routeCount": len(route_ids),
        },
    }


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str) -> Response:
    try:
        store.delete_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    return Response(status_code=204)


@router.post("/scenarios/{scenario_id}/activate")
def activate_scenario(scenario_id: str) -> Dict[str, Any]:
    _ensure_runtime_master_data(scenario_id)
    try:
        scenario = _ensure_scenario_bootstrap_persisted(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)
    context = store.set_active_scenario(scenario_id)
    return {
        "activeScenarioId": scenario_id,
        "scenarioName": scenario.get("name"),
        "selectedOperatorId": scenario.get("operatorId"),
        "availableModules": [
            "planning",
            "simulation",
            "dispatch",
            "results",
            "public-data",
        ],
        "lastOpenedPage": context.get("lastOpenedPage"),
        "updatedAt": context.get("updatedAt"),
    }


@router.get("/app/context")
def get_app_context() -> Dict[str, Any]:
    context = store.get_app_context()
    scenario_id = context.get("activeScenarioId")
    scenario = None
    if isinstance(scenario_id, str):
        try:
            scenario = store.get_scenario(scenario_id)
        except (KeyError, RuntimeError):
            context = store.set_active_scenario(
                None,
                last_opened_page=context.get("lastOpenedPage"),
            )
            scenario_id = None
    if not scenario and isinstance(scenario_id, str):
        try:
            scenario = store.get_scenario(scenario_id)
        except (KeyError, RuntimeError):
            scenario = None

    scenario_name = None
    scenario_operator = None
    if isinstance(scenario, dict):
        scenario_name = scenario.get("name")
        scenario_operator = scenario.get("operatorId")

    return {
        "activeScenarioId": scenario_id,
        "scenarioName": scenario_name,
        "selectedOperatorId": context.get("selectedOperatorId")
        or scenario_operator,
        "availableModules": [
            "planning",
            "simulation",
            "dispatch",
            "results",
            "public-data",
        ],
        "lastOpenedPage": context.get("lastOpenedPage"),
        "updatedAt": context.get("updatedAt"),
    }


# ── Timetable ──────────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/timetable")
def get_timetable(
    scenario_id: str,
    service_id: Optional[str] = Query(
        default=None, description="Filter by service_id (WEEKDAY / SAT / SUN_HOL)"
    ),
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        le=_MAX_PAGE_LIMIT,
        description="Optional page size. Omit to return all rows.",
    ),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    try:
        imports = store.get_timetable_import_meta(scenario_id)
        rows = store.get_field(scenario_id, "timetable_rows") or []
        if not rows:
            doc = store.get_scenario_document(scenario_id)
            shard_rows = _load_shard_timetable_rows(
                scenario_id,
                doc,
                service_id=service_id,
            )
            if shard_rows is not None:
                paged_rows, page_limit = _paginate_items(shard_rows, limit, offset)
                return {
                    "items": paged_rows,
                    "total": len(shard_rows),
                    "limit": page_limit,
                    "offset": offset,
                    "meta": {"imports": imports, "source": "tokyu_shards"},
                }
        if limit is not None:
            paged_rows = (
                store.page_timetable_rows(
                    scenario_id,
                    offset=offset,
                    limit=limit,
                    service_id=service_id,
                )
                if service_id is not None
                else store.page_field_rows(
                    scenario_id,
                    "timetable_rows",
                    offset=offset,
                    limit=limit,
                )
            )
            total = (
                store.count_timetable_rows(scenario_id, service_id=service_id)
                if service_id is not None
                else store.count_field_rows(scenario_id, "timetable_rows")
            )
            return {
                "items": paged_rows,
                "total": total,
                "limit": limit,
                "offset": offset,
                "meta": {"imports": imports},
            }
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)
    if service_id:
        rows = [r for r in rows if r.get("service_id", "WEEKDAY") == service_id]
    paged_rows, page_limit = _paginate_items(rows, limit, offset)
    total = len(rows)
    return {
        "items": paged_rows,
        "total": total,
        "limit": page_limit,
        "offset": offset,
        "meta": {"imports": imports},
    }


@router.get("/scenarios/{scenario_id}/timetable/summary")
def get_timetable_summary(scenario_id: str) -> Dict[str, Any]:
    try:
        summary = store.get_field_summary(scenario_id, "timetable_rows")
        if summary is not None:
            return {"item": summary}
        rows = store.get_field(scenario_id, "timetable_rows") or []
        imports = store.get_timetable_import_meta(scenario_id)
        if not rows:
            doc = store.get_scenario_document(scenario_id)
            scope_params = _shard_scope_params(scenario_id, doc)
            if scope_params is not None:
                shard_summary = build_timetable_summary_for_scope(
                    dataset_id=scope_params["dataset_id"],
                    route_ids=scope_params["route_ids"],
                    depot_ids=scope_params["depot_ids"],
                    service_ids=scope_params["service_ids"],
                )
                if shard_summary is not None:
                    return {"item": shard_summary}
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)
    return {"item": _build_timetable_summary(rows, imports)}


@router.put("/scenarios/{scenario_id}/timetable")
def update_timetable(scenario_id: str, body: UpdateTimetableBody) -> Dict[str, Any]:
    try:
        rows = [r.model_dump() for r in body.rows]
        store.set_field(scenario_id, "timetable_rows", rows, invalidate_dispatch=True)
        return {"items": rows, "total": len(rows)}
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


@router.post("/scenarios/{scenario_id}/timetable/import-csv")
def import_timetable_csv(scenario_id: str, body: ImportCsvBody) -> Dict[str, Any]:
    """
    Parse CSV text and replace the scenario's timetable rows.
    Expected columns (in any order):
      trip_id (optional), route_id, service_id, direction, canonicalDirection,
      routeVariantType, origin, destination, origin_stop_id, destination_stop_id,
      departure, arrival, distance_km, allowed_vehicle_types
    allowed_vehicle_types may be semicolon-separated: BEV;ICE
    """
    try:
        store.get_scenario(scenario_id)  # verify exists
    except KeyError:
        raise _not_found(scenario_id)

    reader = csv.DictReader(io.StringIO(body.content.strip()))
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []

    for i, raw in enumerate(reader, start=2):  # 2 = first data row
        try:
            avt_raw = raw.get("allowed_vehicle_types", "BEV;ICE").strip()
            avt = [v.strip() for v in avt_raw.replace(",", ";").split(";") if v.strip()]
            direction = _normalize_direction(raw.get("direction", "outbound").strip() or "outbound")
            row: Dict[str, Any] = {
                "route_id": raw.get("route_id", "").strip(),
                "service_id": raw.get("service_id", "WEEKDAY").strip() or "WEEKDAY",
                "direction": direction,
                "canonicalDirection": _normalize_direction(
                    raw.get("canonicalDirection", raw.get("canonical_direction", "")).strip() or direction
                ),
                "routeVariantType": _normalize_variant_type(
                    raw.get("routeVariantType", raw.get("route_variant_type", "")).strip() or "unknown"
                ),
                "trip_index": i - 2,
                "origin": raw.get("origin", raw.get("from_stop_id", "")).strip(),
                "destination": raw.get(
                    "destination", raw.get("to_stop_id", "")
                ).strip(),
                "origin_stop_id": raw.get("origin_stop_id", "").strip() or None,
                "destination_stop_id": raw.get("destination_stop_id", "").strip() or None,
                "departure": raw.get("departure", raw.get("dep_time", "")).strip(),
                "arrival": raw.get("arrival", raw.get("arr_time", "")).strip(),
                "distance_km": float(
                    raw.get("distance_km", raw.get("dist_km", 0)) or 0
                ),
                "allowed_vehicle_types": avt if avt else ["BEV", "ICE"],
            }
            if not row["route_id"]:
                errors.append(f"Row {i}: route_id is required")
                continue
            if not row["departure"] or not row["arrival"]:
                errors.append(f"Row {i}: departure and arrival are required")
                continue
            rows.append(row)
        except Exception as exc:
            errors.append(f"Row {i}: {exc}")

    if errors:
        raise HTTPException(
            status_code=422, detail={"errors": errors, "parsed": len(rows)}
        )

    store.set_field(scenario_id, "timetable_rows", rows, invalidate_dispatch=True)
    return {"items": rows, "total": len(rows)}




@router.get("/scenarios/{scenario_id}/stop-timetables")
def get_stop_timetables(
    scenario_id: str,
    stop_id: Optional[str] = Query(default=None),
    service_id: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        le=_MAX_PAGE_LIMIT,
        description="Optional page size. Omit to return all stop timetables.",
    ),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    try:
        items = store.get_field(scenario_id, "stop_timetables") or []
    except KeyError:
        raise _not_found(scenario_id)

    if stop_id:
        items = [item for item in items if item.get("stopId") == stop_id]
    if service_id:
        items = [item for item in items if item.get("service_id") == service_id]
    paged_items, page_limit = _paginate_items(items, limit, offset)

    return {
        "items": paged_items,
        "total": len(items),
        "limit": page_limit,
        "offset": offset,
        "meta": {"imports": store.get_stop_timetable_import_meta(scenario_id)},
    }


@router.get("/scenarios/{scenario_id}/stop-timetables/summary")
def get_stop_timetables_summary(scenario_id: str) -> Dict[str, Any]:
    try:
        items = store.get_field(scenario_id, "stop_timetables") or []
        if not items:
            doc = store.get_scenario_document(scenario_id)
            scope_params = _shard_scope_params(scenario_id, doc)
            if scope_params is not None:
                shard_summary = build_stop_timetable_summary_for_scope(
                    dataset_id=scope_params["dataset_id"],
                    route_ids=scope_params["route_ids"],
                    depot_ids=scope_params["depot_ids"],
                    service_ids=scope_params["service_ids"],
                )
                if shard_summary is not None:
                    return {"item": shard_summary}
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)
    imports = store.get_stop_timetable_import_meta(scenario_id)
    return {"item": _build_stop_timetable_summary(items, imports)}


@router.get("/scenarios/{scenario_id}/timetable/export-csv")
def export_timetable_csv(
    scenario_id: str,
    service_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """
    Export timetable rows as CSV text (JSON envelope so the client can name the file).
    """
    try:
        rows = store.get_field(scenario_id, "timetable_rows")
    except KeyError:
        raise _not_found(scenario_id)
    rows = rows or []
    if service_id:
        rows = [r for r in rows if r.get("service_id", "WEEKDAY") == service_id]

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for i, row in enumerate(rows):
        writer.writerow(
            {
                "trip_id": row.get("trip_id", f"trip_{i:04d}"),
                "route_id": row.get("route_id", ""),
                "service_id": row.get("service_id", "WEEKDAY"),
                "direction": row.get("direction", "outbound"),
                "origin": row.get("origin", ""),
                "destination": row.get("destination", ""),
                "departure": row.get("departure", ""),
                "arrival": row.get("arrival", ""),
                "distance_km": row.get("distance_km", 0),
                "allowed_vehicle_types": ";".join(row.get("allowed_vehicle_types", [])),
            }
        )

    tag = f"_{service_id}" if service_id else ""
    return {
        "content": buf.getvalue(),
        "filename": f"timetable{tag}.csv",
        "rows": len(rows),
    }


# ── Rules (read-only from static data for now) ─────────────────


@router.get("/scenarios/{scenario_id}/deadhead-rules")
def get_deadhead_rules(scenario_id: str) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)  # verify exists
    except KeyError:
        raise _not_found(scenario_id)
    items = store.get_deadhead_rules(scenario_id)
    return {"items": items, "total": len(items)}


@router.get("/scenarios/{scenario_id}/turnaround-rules")
def get_turnaround_rules(scenario_id: str) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    items = store.get_turnaround_rules(scenario_id)
    return {"items": items, "total": len(items)}
