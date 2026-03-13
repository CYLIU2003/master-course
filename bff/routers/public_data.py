from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from bff.services import transit_catalog
from bff.services.gtfs_import import DEFAULT_GTFS_FEED_PATH
from bff.services.odpt_routes import DEFAULT_OPERATOR
from bff.store import scenario_store as store

router = APIRouter(tags=["public-data"])

PublicSourceType = Literal["odpt", "gtfs"]
FetchMode = Literal["incremental", "full"]
CompareMode = Literal["new_only", "new_and_update", "full"]
SyncMode = Literal["preview_only", "insert_only", "insert_and_update", "full_resync"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _not_found(kind: str, value: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} '{value}' not found")


def _ensure_scenario(scenario_id: str) -> None:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found("Scenario", scenario_id)
    except RuntimeError as e:
        if "artifacts are incomplete" in str(e):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "INCOMPLETE_ARTIFACT",
                    "message": str(e)
                }
            )
        raise


def _hash_payload(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _field_diff(old_value: Dict[str, Any], new_value: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    diff: Dict[str, Dict[str, Any]] = {}
    keys = set(old_value) | set(new_value)
    for key in sorted(keys):
        if old_value.get(key) != new_value.get(key):
            diff[key] = {"old": old_value.get(key), "new": new_value.get(key)}
    return diff


def _composite_key(*parts: Any) -> str:
    return "|".join(str(part or "") for part in parts)


def _entity_specs() -> Dict[str, Dict[str, Any]]:
    return {
        "routes": {
            "scenario_field": "routes",
            "source_field": "source",
            "key": lambda item: str(item.get("id") or ""),
            "display": lambda item: str(item.get("name") or item.get("routeCode") or item.get("id") or ""),
        },
        "stops": {
            "scenario_field": "stops",
            "source_field": "source",
            "key": lambda item: str(item.get("id") or ""),
            "display": lambda item: str(item.get("name") or item.get("id") or ""),
        },
        "trips": {
            "scenario_field": "timetable_rows",
            "source_field": "source",
            "key": lambda item: str(
                item.get("trip_id")
                or _composite_key(
                    item.get("route_id"),
                    item.get("service_id"),
                    item.get("direction"),
                    item.get("departure"),
                    item.get("arrival"),
                )
            ),
            "display": lambda item: str(item.get("trip_id") or item.get("route_id") or ""),
        },
        "stop_times": {
            "scenario_field": "stop_timetables",
            "source_field": "source",
            "key": lambda item: str(
                item.get("id")
                or _composite_key(
                    item.get("stop_id") or item.get("stopId"),
                    item.get("route_id") or item.get("routeId"),
                    item.get("service_id"),
                    item.get("time"),
                    item.get("trip_id") or item.get("tripId"),
                )
            ),
            "display": lambda item: str(item.get("stopName") or item.get("stop_id") or item.get("stopId") or ""),
        },
        "service_calendars": {
            "scenario_field": "calendar",
            "source_field": "source",
            "key": lambda item: str(item.get("service_id") or ""),
            "display": lambda item: str(item.get("name") or item.get("service_id") or ""),
        },
        "calendar_dates": {
            "scenario_field": "calendar_dates",
            "source_field": "source",
            "key": lambda item: _composite_key(item.get("date"), item.get("service_id")),
            "display": lambda item: _composite_key(item.get("date"), item.get("service_id")),
        },
    }


def _normalize_entities(bundle: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "routes": [dict(item) for item in bundle.get("routes") or []],
        "stops": [dict(item) for item in bundle.get("stops") or []],
        "trips": [dict(item) for item in bundle.get("timetable_rows") or []],
        "stop_times": [dict(item) for item in bundle.get("stop_timetables") or []],
        "service_calendars": [dict(item) for item in bundle.get("calendar_entries") or []],
        "calendar_dates": [dict(item) for item in bundle.get("calendar_date_entries") or []],
    }


def _quality_summary(entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    return {
        "route_total": len(entities["routes"]),
        "route_with_stops_linked": sum(1 for item in entities["routes"] if item.get("stopSequence")),
        "route_with_timetable_linked": sum(1 for item in entities["routes"] if int(item.get("tripCount") or 0) > 0),
        "stop_total": len(entities["stops"]),
        "trip_total": len(entities["trips"]),
        "stop_time_total": len(entities["stop_times"]),
        "service_calendar_total": len(entities["service_calendars"]),
        "calendar_date_total": len(entities["calendar_dates"]),
    }


def _find_by_id(items: Iterable[Dict[str, Any]], item_id: str) -> Dict[str, Any]:
    for item in items:
        if str(item.get("id")) == item_id:
            return item
    raise KeyError(item_id)


def _save_public_state(scenario_id: str, public_state: Dict[str, Any]) -> Dict[str, Any]:
    return store.set_public_data_state(scenario_id, public_state)


def _source_label(source_type: PublicSourceType) -> str:
    return "odpt" if source_type == "odpt" else "gtfs"


def _load_public_bundle(
    source_type: PublicSourceType,
    *,
    dataset_ref: str,
    force_refresh: bool,
) -> Dict[str, Any]:
    if source_type == "odpt":
        if force_refresh:
            return transit_catalog.refresh_odpt_snapshot(
                operator=dataset_ref,
                dump=True,
                force_refresh=True,
                ttl_sec=3600,
            )
        bundle = transit_catalog.load_existing_odpt_snapshot(operator=dataset_ref)
        if bundle is not None:
            return bundle
        raise RuntimeError(
            "No saved ODPT snapshot is available. Run `python3 catalog_update_app.py refresh odpt` "
            "or retry with force_refresh=true."
        )

    if force_refresh:
        return transit_catalog.refresh_gtfs_snapshot(feed_path=dataset_ref)
    bundle = transit_catalog.load_existing_gtfs_snapshot(feed_path=dataset_ref)
    if bundle is not None:
        return bundle
    raise RuntimeError(
        "No saved GTFS snapshot is available. Run `python3 catalog_update_app.py refresh gtfs` "
        "or retry with force_refresh=true."
    )


class PublicDataFetchRequest(BaseModel):
    source_type: PublicSourceType
    operator_id: Optional[str] = None
    operatorScope: Optional[str] = None
    fetch_mode: FetchMode = "incremental"
    resource_targets: List[str] = Field(default_factory=list)
    force_refresh: bool = False
    forceRefresh: bool = False


class NormalizeRequest(BaseModel):
    raw_snapshot_id: str
    rebuild: bool = False


class DiffRequest(BaseModel):
    normalized_snapshot_id: str
    compare_mode: CompareMode = "new_and_update"
    compare_targets: List[str] = Field(
        default_factory=lambda: [
            "routes",
            "stops",
            "trips",
            "stop_times",
            "service_calendars",
            "calendar_dates",
        ]
    )
    include_timetable_diff: bool = False
    include_stop_sequence_diff: bool = True


class SyncRequest(BaseModel):
    diff_session_id: str
    sync_mode: SyncMode = "insert_and_update"
    selected_diff_ids: Optional[List[str]] = None
    dry_run: bool = False


@router.post("/scenarios/{scenario_id}/public-data/fetch")
def fetch_public_data(scenario_id: str, body: PublicDataFetchRequest) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    force_refresh = bool(body.force_refresh or body.forceRefresh)
    try:
        if body.source_type == "odpt":
            operator = body.operator_id or body.operatorScope or DEFAULT_OPERATOR
            dataset_ref = operator
        else:
            dataset_ref = body.operator_id or body.operatorScope or DEFAULT_GTFS_FEED_PATH
        bundle = _load_public_bundle(
            body.source_type,
            dataset_ref=dataset_ref,
            force_refresh=force_refresh,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Public data fetch failed for {body.source_type}: {exc}. "
                "Retry later or use a saved/catalog snapshot."
            ),
        ) from exc

    snapshot = bundle.get("snapshot") or {}
    meta = dict(bundle.get("meta") or {})
    fetched_counts = {
        "routes": len(bundle.get("routes") or []),
        "stops": len(bundle.get("stops") or []),
        "timetableRows": len(bundle.get("timetable_rows") or []),
        "stopTimetables": len(bundle.get("stop_timetables") or []),
        "calendarEntries": len(bundle.get("calendar_entries") or []),
        "calendarDateEntries": len(bundle.get("calendar_date_entries") or []),
    }

    public_state = store.get_public_data_state(scenario_id)
    # Build a lightweight meta summary — never include raw payload data
    meta_summary = {
        "source": meta.get("source"),
        "operator": meta.get("operator"),
        "snapshotSource": meta.get("snapshotSource"),
        "snapshotMode": meta.get("snapshotMode"),
        "generatedAt": meta.get("generatedAt"),
        "refreshedAt": meta.get("refreshedAt"),
        "counts": dict(meta.get("counts") or {}),
    }
    record = {
        "id": _new_id("raw"),
        "source_type": body.source_type,
        "dataset_ref": dataset_ref,
        "snapshotKey": snapshot.get("snapshotKey"),
        "fetch_mode": body.fetch_mode,
        "resource_targets": body.resource_targets,
        "fingerprint": snapshot.get("signature") or _hash_payload(fetched_counts),
        "fetched_counts": fetched_counts,
        "warnings": list(meta.get("warnings") or []),
        "started_at": meta.get("generatedAt") or _now_iso(),
        "completed_at": _now_iso(),
        "meta": meta_summary,
    }
    public_state["raw_snapshots"] = [
        item
        for item in public_state.get("raw_snapshots") or []
        if item.get("snapshotKey") != record["snapshotKey"]
    ]
    public_state["raw_snapshots"].append(record)
    _save_public_state(scenario_id, public_state)
    return {
        **record,
        "snapshot_id": record["id"],
        "snapshotId": record["id"],
        "fetchedCounts": record["fetched_counts"],
        "startedAt": record["started_at"],
        "completedAt": record["completed_at"],
    }


@router.post("/scenarios/{scenario_id}/public-data/normalize")
def normalize_public_data(scenario_id: str, body: NormalizeRequest) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    public_state = store.get_public_data_state(scenario_id)
    try:
        raw_snapshot = _find_by_id(public_state.get("raw_snapshots") or [], body.raw_snapshot_id)
    except KeyError:
        raise _not_found("Raw snapshot", body.raw_snapshot_id)

    snapshot_key = raw_snapshot.get("snapshotKey")
    if not snapshot_key:
        raise HTTPException(status_code=422, detail="Raw snapshot is missing snapshotKey")

    bundle = transit_catalog.load_snapshot_bundle(snapshot_key)
    entities = _normalize_entities(bundle)
    quality_summary = _quality_summary(entities)
    record = {
        "id": _new_id("norm"),
        "raw_snapshot_id": body.raw_snapshot_id,
        "snapshotKey": snapshot_key,
        "source_type": raw_snapshot.get("source_type"),
        "entity_counts": {key: len(value) for key, value in entities.items()},
        "quality_summary": quality_summary,
        "warnings": list((bundle.get("meta") or {}).get("warnings") or []),
        "entities": entities,
        "normalized_at": _now_iso(),
    }
    public_state["normalized_snapshots"] = [
        item
        for item in public_state.get("normalized_snapshots") or []
        if item.get("raw_snapshot_id") != body.raw_snapshot_id
    ]
    public_state["normalized_snapshots"].append(record)
    _save_public_state(scenario_id, public_state)
    return {
        "normalized_snapshot_id": record["id"],
        "normalizedSnapshotId": record["id"],
        "entity_counts": record["entity_counts"],
        "entityCounts": record["entity_counts"],
        "quality_summary": quality_summary,
        "qualitySummary": quality_summary,
        "warnings": record["warnings"],
    }


@router.post("/scenarios/{scenario_id}/public-data/diff")
def diff_public_data(scenario_id: str, body: DiffRequest) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    public_state = store.get_public_data_state(scenario_id)
    try:
        normalized_snapshot = _find_by_id(
            public_state.get("normalized_snapshots") or [], body.normalized_snapshot_id
        )
    except KeyError:
        raise _not_found("Normalized snapshot", body.normalized_snapshot_id)

    specs = _entity_specs()
    warnings: List[str] = []
    items: List[Dict[str, Any]] = []
    source_type = str(normalized_snapshot.get("source_type") or "odpt")
    source_label = _source_label(source_type)  # type: ignore[arg-type]

    for entity_type in body.compare_targets:
        spec = specs.get(entity_type)
        if spec is None:
            warnings.append(f"Unsupported compare target skipped: {entity_type}")
            continue
        incoming_items = list((normalized_snapshot.get("entities") or {}).get(entity_type) or [])
        scenario_field = spec["scenario_field"]
        existing_items = list(store.get_field(scenario_id, scenario_field) or [])
        source_field = spec["source_field"]
        existing_index = {
            spec["key"](item): item
            for item in existing_items
            if spec["key"](item) and (
                scenario_field in {"calendar", "calendar_dates"} or item.get(source_field) == source_label
            )
        }
        incoming_index = {
            spec["key"](item): item for item in incoming_items if spec["key"](item)
        }

        for entity_key, incoming in incoming_index.items():
            existing = existing_index.get(entity_key)
            if existing is None:
                items.append(
                    {
                        "id": _new_id("diff"),
                        "entity_type": entity_type,
                        "entity_key": entity_key,
                        "display_name": spec["display"](incoming),
                        "change_type": "new",
                        "old_value": None,
                        "new_value": incoming,
                        "field_diff": {},
                        "conflict_flags": {},
                        "suggested_action": "insert",
                        "status": "pending",
                    }
                )
                continue

            old_hash = _hash_payload(existing)
            new_hash = _hash_payload(incoming)
            if old_hash == new_hash:
                continue
            if body.compare_mode == "new_only":
                continue
            field_diff = _field_diff(existing, incoming)
            conflict_flags = {
                "manual_override": bool(
                    entity_type == "routes"
                    and any(
                        str(assignment.get("routeId")) == entity_key
                        and str(assignment.get("assignmentType")) == "manual_override"
                        for assignment in store.list_route_depot_assignments(scenario_id)
                    )
                )
            }
            change_type = "conflict" if conflict_flags["manual_override"] else "changed"
            suggested_action = "review" if change_type == "conflict" else "update"
            items.append(
                {
                    "id": _new_id("diff"),
                    "entity_type": entity_type,
                    "entity_key": entity_key,
                    "display_name": spec["display"](incoming),
                    "change_type": change_type,
                    "old_value": existing,
                    "new_value": incoming,
                    "field_diff": field_diff,
                    "conflict_flags": conflict_flags,
                    "suggested_action": suggested_action,
                    "status": "pending",
                }
            )

        if body.compare_mode == "full":
            for entity_key, existing in existing_index.items():
                if entity_key in incoming_index:
                    continue
                items.append(
                    {
                        "id": _new_id("diff"),
                        "entity_type": entity_type,
                        "entity_key": entity_key,
                        "display_name": spec["display"](existing),
                        "change_type": "deleted_candidate",
                        "old_value": existing,
                        "new_value": None,
                        "field_diff": {},
                        "conflict_flags": {},
                        "suggested_action": "skip",
                        "status": "pending",
                    }
                )

    summary = {
        "new_count": sum(1 for item in items if item["change_type"] == "new"),
        "changed_count": sum(1 for item in items if item["change_type"] == "changed"),
        "deleted_candidate_count": sum(1 for item in items if item["change_type"] == "deleted_candidate"),
        "conflict_count": sum(1 for item in items if item["change_type"] == "conflict"),
    }
    session = {
        "id": _new_id("diffs"),
        "normalized_snapshot_id": body.normalized_snapshot_id,
        "compare_mode": body.compare_mode,
        "created_at": _now_iso(),
        "summary": summary,
        "items": items,
        "warnings": warnings,
        "conflicts": [item for item in items if item["change_type"] == "conflict"],
        "suggested_actions": [
            {
                "diff_id": item["id"],
                "action": item["suggested_action"],
            }
            for item in items
        ],
    }
    public_state["diff_sessions"] = [
        item
        for item in public_state.get("diff_sessions") or []
        if item.get("normalized_snapshot_id") != body.normalized_snapshot_id
    ]
    public_state["diff_sessions"].append(session)
    warnings_state = list(public_state.get("warnings") or [])
    if summary["conflict_count"] > 0:
        warnings_state.append(
            {
                "id": _new_id("warn"),
                "severity": "warning",
                "code": "public_data_conflict",
                "message": f"{summary['conflict_count']} conflict(s) detected during diff.",
                "entity_type": "diff_session",
                "entity_key": session["id"],
                "snapshot_id": body.normalized_snapshot_id,
                "created_at": _now_iso(),
            }
        )
    public_state["warnings"] = warnings_state
    _save_public_state(scenario_id, public_state)
    return {
        "diff_session_id": session["id"],
        "diffSessionId": session["id"],
        "summary": summary,
        "warnings": warnings,
        "conflicts": session["conflicts"],
        "suggestedActions": session["suggested_actions"],
    }


@router.get("/scenarios/{scenario_id}/public-data/diff/{diff_session_id}")
def get_diff_session(scenario_id: str, diff_session_id: str) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    public_state = store.get_public_data_state(scenario_id)
    try:
        session = _find_by_id(public_state.get("diff_sessions") or [], diff_session_id)
    except KeyError:
        raise _not_found("Diff session", diff_session_id)
    return {
        "diff_session_id": session["id"],
        "summary": session["summary"],
        "warnings": session.get("warnings") or [],
        "conflicts": session.get("conflicts") or [],
        "suggestedActions": session.get("suggested_actions") or [],
    }


@router.get("/scenarios/{scenario_id}/public-data/diff/{diff_session_id}/items")
def list_diff_items(
    scenario_id: str,
    diff_session_id: str,
    entity_type: Optional[str] = Query(default=None),
    change_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    public_state = store.get_public_data_state(scenario_id)
    try:
        session = _find_by_id(public_state.get("diff_sessions") or [], diff_session_id)
    except KeyError:
        raise _not_found("Diff session", diff_session_id)
    items = list(session.get("items") or [])
    if entity_type:
        items = [item for item in items if item.get("entity_type") == entity_type]
    if change_type:
        items = [item for item in items if item.get("change_type") == change_type]
    sliced = items[offset : offset + limit]
    return {"items": sliced, "total": len(items)}


@router.get("/scenarios/{scenario_id}/public-data/diff/{diff_session_id}/items/{item_id}")
def get_diff_item_detail(scenario_id: str, diff_session_id: str, item_id: str) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    public_state = store.get_public_data_state(scenario_id)
    try:
        session = _find_by_id(public_state.get("diff_sessions") or [], diff_session_id)
    except KeyError:
        raise _not_found("Diff session", diff_session_id)
    try:
        item = _find_by_id(session.get("items") or [], item_id)
    except KeyError:
        raise _not_found("Diff item", item_id)
    return item


def _apply_entity_changes(
    scenario_id: str,
    entity_type: str,
    source_label: str,
    apply_items: List[Dict[str, Any]],
    sync_mode: SyncMode,
) -> Tuple[int, int, int]:
    specs = _entity_specs()
    spec = specs[entity_type]
    inserted = 0
    updated = 0
    skipped = 0

    if entity_type == "routes":
        existing = {
            str(item.get("id")): dict(item)
            for item in store.list_routes(scenario_id)
            if item.get("source") == source_label and item.get("id") is not None
        }
        for diff_item in apply_items:
            if diff_item["change_type"] == "deleted_candidate":
                if sync_mode == "full_resync":
                    existing.pop(diff_item["entity_key"], None)
                else:
                    skipped += 1
                continue
            payload = dict(diff_item.get("new_value") or {})
            payload["source"] = source_label
            if diff_item["entity_key"] in existing:
                updated += 1
            else:
                inserted += 1
            existing[diff_item["entity_key"]] = payload
        store.replace_routes_from_source(
            scenario_id,
            source_label,
            list(existing.values()),
            import_meta=store.get_route_import_meta(scenario_id, source_label),
        )
        return inserted, updated, skipped

    if entity_type == "stops":
        existing = {
            str(item.get("id")): dict(item)
            for item in store.list_stops(scenario_id)
            if item.get("source") == source_label and item.get("id") is not None
        }
        for diff_item in apply_items:
            if diff_item["change_type"] == "deleted_candidate":
                if sync_mode == "full_resync":
                    existing.pop(diff_item["entity_key"], None)
                else:
                    skipped += 1
                continue
            payload = dict(diff_item.get("new_value") or {})
            payload["source"] = source_label
            if diff_item["entity_key"] in existing:
                updated += 1
            else:
                inserted += 1
            existing[diff_item["entity_key"]] = payload
        store.replace_stops_from_source(
            scenario_id,
            source_label,
            list(existing.values()),
            import_meta=store.get_stop_import_meta(scenario_id, source_label),
        )
        return inserted, updated, skipped

    if entity_type == "trips":
        payloads = []
        for diff_item in apply_items:
            if diff_item["change_type"] == "deleted_candidate":
                skipped += 1
                continue
            payload = dict(diff_item.get("new_value") or {})
            payload["source"] = source_label
            payloads.append(payload)
            if diff_item["change_type"] == "new":
                inserted += 1
            else:
                updated += 1
        if payloads:
            store.upsert_timetable_rows_from_source(
                scenario_id,
                source_label,
                payloads,
                replace_existing_source=(sync_mode == "full_resync"),
            )
        return inserted, updated, skipped

    if entity_type == "stop_times":
        payloads = []
        for diff_item in apply_items:
            if diff_item["change_type"] == "deleted_candidate":
                skipped += 1
                continue
            payload = dict(diff_item.get("new_value") or {})
            payload["source"] = source_label
            payloads.append(payload)
            if diff_item["change_type"] == "new":
                inserted += 1
            else:
                updated += 1
        if payloads:
            store.upsert_stop_timetables_from_source(
                scenario_id,
                source_label,
                payloads,
                replace_existing_source=(sync_mode == "full_resync"),
            )
        return inserted, updated, skipped

    scenario_field = spec["scenario_field"]
    current_items = list(store.get_field(scenario_id, scenario_field) or [])
    current_index = {spec["key"](item): dict(item) for item in current_items if spec["key"](item)}
    for diff_item in apply_items:
        if diff_item["change_type"] == "deleted_candidate":
            if sync_mode == "full_resync":
                current_index.pop(diff_item["entity_key"], None)
            else:
                skipped += 1
            continue
        payload = dict(diff_item.get("new_value") or {})
        if diff_item["entity_key"] in current_index:
            updated += 1
        else:
            inserted += 1
        current_index[diff_item["entity_key"]] = payload
    store.set_field(scenario_id, scenario_field, list(current_index.values()), invalidate_dispatch=True)
    return inserted, updated, skipped


@router.post("/scenarios/{scenario_id}/public-data/sync")
def sync_public_data(scenario_id: str, body: SyncRequest) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    public_state = store.get_public_data_state(scenario_id)
    try:
        session = _find_by_id(public_state.get("diff_sessions") or [], body.diff_session_id)
    except KeyError:
        raise _not_found("Diff session", body.diff_session_id)

    if body.sync_mode == "preview_only" or body.dry_run:
        return {
            "sync_history_id": _new_id("sync_preview"),
            "inserted_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "conflict_count": len(session.get("conflicts") or []),
            "warnings": ["Dry-run only; no scenario data was changed."],
        }

    selected_ids = set(body.selected_diff_ids or [])
    diff_items = list(session.get("items") or [])
    if selected_ids:
        diff_items = [item for item in diff_items if item.get("id") in selected_ids]

    if body.sync_mode == "insert_only":
        diff_items = [item for item in diff_items if item.get("change_type") == "new"]
    else:
        diff_items = [item for item in diff_items if item.get("change_type") != "conflict"]

    normalized_snapshot = _find_by_id(
        public_state.get("normalized_snapshots") or [], session["normalized_snapshot_id"]
    )
    source_type = str(normalized_snapshot.get("source_type") or "odpt")
    source_label = _source_label(source_type)  # type: ignore[arg-type]

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in diff_items:
        grouped.setdefault(str(item.get("entity_type")), []).append(item)

    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    conflict_count = len(session.get("conflicts") or [])
    change_logs: List[Dict[str, Any]] = list(public_state.get("change_logs") or [])

    for entity_type, entity_items in grouped.items():
        inserted, updated, skipped = _apply_entity_changes(
            scenario_id,
            entity_type,
            source_label,
            entity_items,
            body.sync_mode,
        )
        inserted_count += inserted
        updated_count += updated
        skipped_count += skipped
        for item in entity_items:
            change_logs.append(
                {
                    "id": _new_id("chg"),
                    "entity_type": entity_type,
                    "entity_key": item.get("entity_key"),
                    "operation_type": item.get("suggested_action"),
                    "before_json": item.get("old_value"),
                    "after_json": item.get("new_value"),
                    "source": source_label,
                    "created_at": _now_iso(),
                }
            )

    history = {
        "id": _new_id("sync"),
        "diff_session_id": body.diff_session_id,
        "sync_mode": body.sync_mode,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "conflict_count": conflict_count,
        "created_at": _now_iso(),
        "actor": "local-user",
    }
    public_state["sync_histories"] = list(public_state.get("sync_histories") or []) + [history]
    public_state["change_logs"] = change_logs
    _save_public_state(scenario_id, public_state)
    return {
        "sync_history_id": history["id"],
        "syncHistoryId": history["id"],
        "inserted_count": inserted_count,
        "insertedCount": inserted_count,
        "updated_count": updated_count,
        "updatedCount": updated_count,
        "skipped_count": skipped_count,
        "skippedCount": skipped_count,
        "conflict_count": conflict_count,
        "conflictCount": conflict_count,
        "warnings": [],
    }


@router.get("/scenarios/{scenario_id}/public-data/sync-history")
def list_sync_history(scenario_id: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    items = list(store.get_public_data_state(scenario_id).get("sync_histories") or [])
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {"items": items[offset : offset + limit], "total": len(items)}


@router.get("/scenarios/{scenario_id}/public-data/sync-history/{history_id}")
def get_sync_history(scenario_id: str, history_id: str) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    try:
        return _find_by_id(store.get_public_data_state(scenario_id).get("sync_histories") or [], history_id)
    except KeyError:
        raise _not_found("Sync history", history_id)


@router.get("/scenarios/{scenario_id}/public-data/warnings")
def list_public_data_warnings(
    scenario_id: str,
    severity: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    items = list(store.get_public_data_state(scenario_id).get("warnings") or [])
    if severity:
        items = [item for item in items if item.get("severity") == severity]
    return {"items": items[offset : offset + limit], "total": len(items)}


@router.get("/scenarios/{scenario_id}/public-data/quality")
def get_public_data_quality(scenario_id: str) -> Dict[str, Any]:
    _ensure_scenario(scenario_id)
    public_state = store.get_public_data_state(scenario_id)
    normalized = list(public_state.get("normalized_snapshots") or [])
    latest = normalized[-1] if normalized else None
    if latest is not None:
        quality = dict(latest.get("quality_summary") or {})
    else:
        routes = store.list_routes(scenario_id)
        quality = {
            "route_total": len(routes),
            "route_with_depot_assigned": sum(1 for item in routes if item.get("depotId")),
            "route_with_stops_linked": sum(1 for item in routes if item.get("stopSequence")),
            "route_with_timetable_linked": sum(1 for item in routes if int(item.get("tripCount") or 0) > 0),
        }
    quality["unresolved_warning_count"] = len(public_state.get("warnings") or [])
    quality["source_freshness"] = {
        "last_raw_snapshot_at": (
            (public_state.get("raw_snapshots") or [])[-1].get("completed_at")
            if public_state.get("raw_snapshots")
            else None
        ),
        "last_normalized_snapshot_at": latest.get("normalized_at") if latest else None,
    }
    return quality
