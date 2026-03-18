#!/usr/bin/env python3
"""
catalog_update_app.py

Standalone data-update app for ODPT / GTFS refresh and scenario sync.

This script is intentionally separate from the main frontend/BFF runtime so
heavy public-data refresh work can be run on demand.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_OPERATOR = "odpt.Operator:TokyuBus"
DEFAULT_GTFS_FEED_PATH = "GTFS/TokyuBus-GTFS"
DEFAULT_TOKYUBUS_PIPELINE_SOURCE_DIR = "./data/raw-odpt"
ALL_RESOURCES = ("routes", "stops", "timetable", "stop-timetables", "calendar")


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _progress_logger(stage: str, payload: Dict[str, Any]) -> None:
    progress = payload.get("progress")
    counts = payload.get("counts") or {}
    if isinstance(progress, dict):
        next_cursor = int(progress.get("nextCursor") or 0)
        total_chunks = int(progress.get("totalChunks") or 0)
        complete = bool(progress.get("complete"))
        label = payload.get("resource") or stage
        suffix = " complete" if complete else ""
        print(
            f"[progress] {label}: chunk {next_cursor}/{total_chunks}{suffix} "
            f"counts={_format_counts(counts)}"
        )
        return
    print(f"[progress] {stage}: {_format_counts(counts)}")


def _format_counts(counts: Dict[str, Any]) -> str:
    if not counts:
        return "-"
    parts = [f"{key}={value}" for key, value in counts.items()]
    return ", ".join(parts)


def _fast_ingest():
    from tools import fast_catalog_ingest

    return fast_catalog_ingest


def _tokyubus_gtfs_pipeline():
    lib_root = Path(__file__).resolve().parent / "data-prep" / "lib"
    if str(lib_root) not in sys.path:
        sys.path.insert(0, str(lib_root))
    from tokyubus_gtfs.pipeline import PipelineConfig, run_pipeline

    return PipelineConfig, run_pipeline


def _data_prep_build_all():
    source_path = Path(__file__).resolve().parent / "data-prep" / "pipeline" / "build_all.py"
    spec = importlib.util.spec_from_file_location("data_prep_build_all_source", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load build_all.py from {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_tokyu_gtfs_db_module():
    source_path = Path(__file__).resolve().parent / "scripts" / "build_tokyu_gtfs_db.py"
    spec = importlib.util.spec_from_file_location("build_tokyu_gtfs_db_source", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load build_tokyu_gtfs_db.py from {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_dataset_ids(value: Optional[str]) -> List[str]:
    if not value:
        return ["tokyu_core", "tokyu_full"]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _normalize_route_code(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_dataset_scope(dataset_id: str) -> Dict[str, Any]:
    path = Path("data") / "seed" / "tokyu" / "datasets" / f"{dataset_id}.json"
    if not path.exists():
        return {"included_depots": [], "included_routes": "ALL"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"included_depots": [], "included_routes": "ALL"}
    return {
        "included_depots": [str(x).strip() for x in payload.get("included_depots") or [] if str(x).strip()],
        "included_routes": payload.get("included_routes", "ALL"),
    }


def _read_route_to_depot_map() -> Dict[str, set[str]]:
    path = Path("data") / "seed" / "tokyu" / "route_to_depot.csv"
    mapping: Dict[str, set[str]] = {}
    if not path.exists():
        return mapping
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            route_code = _normalize_route_code(row.get("route_code"))
            depot_id = str(row.get("depot_id") or "").strip()
            if not route_code or not depot_id:
                continue
            mapping.setdefault(route_code, set()).add(depot_id)
    return mapping


def _route_allowed_for_dataset(
    route: Dict[str, Any],
    *,
    included_depots: set[str],
    included_routes: set[str] | None,
    route_to_depot: Dict[str, set[str]],
    dataset_id: str,
) -> bool:
    route_code = _normalize_route_code(
        route.get("routeCode")
        or route.get("routeFamilyCode")
        or route.get("routeLabel")
        or route.get("name")
    )
    if included_routes is not None and route_code not in included_routes:
        return False
    if not included_depots:
        return True
    mapped = route_to_depot.get(route_code) or set()
    if not mapped:
        # unknown mapping is kept for full dataset and dropped for scoped datasets
        return dataset_id == "tokyu_full"
    return len(mapped.intersection(included_depots)) > 0


def _rebuild_from_catalog_fast(
    *,
    dataset_id: str,
    source_dir: Path,
) -> Dict[str, Any]:
    import pandas as pd

    normalized_dir = source_dir / "normalized"
    required = [
        normalized_dir / "routes.jsonl",
        normalized_dir / "trips.jsonl",
        normalized_dir / "stops.jsonl",
        normalized_dir / "stop_times.jsonl",
        normalized_dir / "busstop_pole_timetables.jsonl",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(
            "catalog-fast normalized files are missing: " + ", ".join(missing)
        )

    route_to_depot = _read_route_to_depot_map()
    scope = _read_dataset_scope(dataset_id)
    included_depots = set(scope["included_depots"])
    included_routes_raw = scope["included_routes"]
    included_routes = None if included_routes_raw == "ALL" else set(str(x).strip() for x in (included_routes_raw or []) if str(x).strip())

    routes_raw = _read_jsonl(normalized_dir / "routes.jsonl")
    trips_raw = _read_jsonl(normalized_dir / "trips.jsonl")
    stops_raw = _read_jsonl(normalized_dir / "stops.jsonl")
    stop_times_raw = _read_jsonl(normalized_dir / "stop_times.jsonl")
    stop_timetables_raw = _read_jsonl(normalized_dir / "busstop_pole_timetables.jsonl")

    routes_scoped = [
        row for row in routes_raw
        if _route_allowed_for_dataset(
            row,
            included_depots=included_depots,
            included_routes=included_routes,
            route_to_depot=route_to_depot,
            dataset_id=dataset_id,
        )
    ]
    route_ids = {str(row.get("id") or "").strip() for row in routes_scoped if str(row.get("id") or "").strip()}

    trips_scoped = [row for row in trips_raw if str(row.get("route_id") or "").strip() in route_ids]
    scope_relaxed = False
    if routes_scoped and not trips_scoped:
        # normalized sources may use route/depot classifications that differ from seed mapping;
        # avoid generating an empty runnable dataset.
        routes_scoped = list(routes_raw)
        route_ids = {str(row.get("id") or "").strip() for row in routes_scoped if str(row.get("id") or "").strip()}
        trips_scoped = [row for row in trips_raw if str(row.get("route_id") or "").strip() in route_ids]
        scope_relaxed = True
    trip_ids = {str(row.get("trip_id") or "").strip() for row in trips_scoped if str(row.get("trip_id") or "").strip()}

    stop_times_scoped = [row for row in stop_times_raw if str(row.get("trip_id") or "").strip() in trip_ids]
    used_stop_ids = {
        str(row.get("stop_id") or "").strip()
        for row in stop_times_scoped
        if str(row.get("stop_id") or "").strip()
    }
    for row in trips_scoped:
        origin = str(row.get("origin") or "").strip()
        destination = str(row.get("destination") or "").strip()
        if origin:
            used_stop_ids.add(origin)
        if destination:
            used_stop_ids.add(destination)

    stops_scoped = [row for row in stops_raw if str(row.get("id") or "").strip() in used_stop_ids]
    stop_timetables_scoped = [
        row for row in stop_timetables_raw if str(row.get("stopId") or row.get("stop_id") or "").strip() in used_stop_ids
    ]

    routes_rows = [
        {
            "id": str(row.get("id") or "").strip(),
            "routeCode": str(row.get("routeCode") or "").strip(),
            "routeLabel": str(row.get("routeLabel") or row.get("name") or row.get("routeCode") or "").strip(),
            "name": str(row.get("name") or row.get("routeLabel") or row.get("routeCode") or "").strip(),
            "source": str(row.get("source") or "catalog_fast").strip(),
            "depotId": row.get("depotId") or row.get("depot_id"),
            "stopSequence": list(row.get("stopSequence") or []),
        }
        for row in routes_scoped
    ]

    trips_rows = [
        {
            "trip_id": str(row.get("trip_id") or "").strip(),
            "route_id": str(row.get("route_id") or "").strip(),
            "service_id": str(row.get("service_id") or "WEEKDAY").strip() or "WEEKDAY",
            "departure": str(row.get("departure") or "").strip(),
            "arrival": str(row.get("arrival") or "").strip(),
            "origin": str(row.get("origin") or "").strip(),
            "destination": str(row.get("destination") or "").strip(),
            "distance_km": float(row.get("distance_km") or 0.0),
            "direction": str(row.get("direction") or "outbound").strip() or "outbound",
            "allowed_vehicle_types": list(row.get("allowed_vehicle_types") or ["BEV", "ICE"]),
            "source": str(row.get("source") or "catalog_fast").strip(),
        }
        for row in trips_scoped
    ]

    timetables_rows = [dict(row) for row in trips_rows]

    stops_rows = [
        {
            "id": str(row.get("id") or "").strip(),
            "code": str(row.get("code") or row.get("id") or "").strip(),
            "name": str(row.get("name") or row.get("id") or "").strip(),
            "lat": row.get("lat"),
            "lon": row.get("lon"),
            "poleNumber": row.get("poleNumber"),
            "source": str(row.get("source") or "catalog_fast").strip(),
        }
        for row in stops_scoped
    ]

    stop_times_rows = [
        {
            "trip_id": str(row.get("trip_id") or "").strip(),
            "stop_id": str(row.get("stop_id") or "").strip(),
            "stop_name": str(row.get("stop_name") or "").strip(),
            "sequence": row.get("sequence"),
            "departure": str(row.get("departure") or "").strip(),
            "arrival": str(row.get("arrival") or "").strip(),
            "source": str(row.get("source") or "catalog_fast").strip(),
        }
        for row in stop_times_scoped
    ]

    stop_timetables_rows = [
        {
            "id": str(row.get("id") or "").strip(),
            "stopId": str(row.get("stopId") or row.get("stop_id") or "").strip(),
            "calendar": str(row.get("calendar") or "").strip(),
            "service_id": str(row.get("service_id") or "WEEKDAY").strip() or "WEEKDAY",
            "items": list(row.get("items") or []),
            "source": str(row.get("source") or "catalog_fast").strip(),
        }
        for row in stop_timetables_scoped
    ]

    built_dir = Path("data") / "built" / dataset_id
    built_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(routes_rows).to_parquet(built_dir / "routes.parquet", index=False)
    pd.DataFrame(trips_rows).to_parquet(built_dir / "trips.parquet", index=False)
    pd.DataFrame(timetables_rows).to_parquet(built_dir / "timetables.parquet", index=False)
    pd.DataFrame(stops_rows).to_parquet(built_dir / "stops.parquet", index=False)
    pd.DataFrame(stop_times_rows).to_parquet(built_dir / "stop_times.parquet", index=False)
    pd.DataFrame(stop_timetables_rows).to_parquet(built_dir / "stop_timetables.parquet", index=False)

    summary_payload = {
        "dataset_id": dataset_id,
        "source_dir": str(source_dir.resolve()),
        "counts": {
            "routes": len(routes_rows),
            "trips": len(trips_rows),
            "timetables": len(timetables_rows),
            "stops": len(stops_rows),
            "stop_times": len(stop_times_rows),
            "stop_timetables": len(stop_timetables_rows),
        },
    }
    (built_dir / "summary.json").write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    artifact_files = [
        "routes.parquet",
        "trips.parquet",
        "timetables.parquet",
        "stops.parquet",
        "stop_times.parquet",
        "stop_timetables.parquet",
        "summary.json",
    ]
    artifact_hashes = {
        name: _sha256_file(built_dir / name)
        for name in artifact_files
        if (built_dir / name).exists()
    }

    manifest = {
        "schema_version": "v1",
        "dataset_id": dataset_id,
        "dataset_version": f"catalog-fast-{int(time.time())}",
        "producer_version": "catalog_fast_fallback",
        "min_runtime_version": "0.1.0",
        "artifact_hashes": artifact_hashes,
        "source": "catalog-fast-normalized",
    }
    (built_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "exitCode": 0,
        "builtDir": str(built_dir.resolve()),
        "fallback": True,
        "scopeRelaxed": scope_relaxed,
        "sourceDir": str(source_dir.resolve()),
        "counts": summary_payload["counts"],
    }


def _rebuild_tokyu_built_datasets(
    *,
    dataset_ids: Sequence[str],
    feed_path: str,
    strict_gtfs_reconciliation: bool,
    source_dir: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        build_all = _data_prep_build_all()
    except Exception:
        build_all = None
    results: Dict[str, Any] = {}
    fallback_source_dir = Path(source_dir or "data/catalog-fast")
    for dataset_id in dataset_ids:
        if build_all is not None:
            exit_code = int(
                build_all.build_dataset(
                    dataset_id,
                    no_fetch=True,
                    force=True,
                    feed_path=feed_path,
                    strict_gtfs_reconciliation=strict_gtfs_reconciliation,
                )
            )
            results[dataset_id] = {
                "exitCode": exit_code,
                "builtDir": str((Path("data") / "built" / dataset_id).resolve()),
                "fallback": False,
            }
            if exit_code != 0:
                raise RuntimeError(
                    f"Built dataset rebuild failed for '{dataset_id}' with exit code {exit_code}."
                )
            continue

        results[dataset_id] = _rebuild_from_catalog_fast(
            dataset_id=dataset_id,
            source_dir=fallback_source_dir,
        )
    return results


def _build_gtfs_sqlite_catalog(
    *,
    dataset_id: str,
    feed_path: str,
    db_path: str,
) -> Dict[str, Any]:
    module = _build_tokyu_gtfs_db_module()
    output_path = module.build_tokyu_gtfs_db(
        Path(db_path),
        dataset_id=dataset_id,
        feed_path=feed_path,
    )
    return {
        "datasetId": dataset_id,
        "dbPath": str(Path(output_path).resolve()),
    }


def _build_odpt_import_meta(
    *,
    dataset: Dict[str, Any],
    operator: str,
    dump: bool,
    quality: Dict[str, Any],
    progress_key: str,
    resource_type: str,
) -> Dict[str, Any]:
    meta = dataset.get("meta", {}) if isinstance(dataset, dict) else {}
    progress = (meta.get("progress") or {}).get(progress_key)
    return {
        "operator": operator,
        "dump": meta.get("effectiveDump", meta.get("dump", dump)),
        "requestedDump": dump,
        "source": "odpt",
        "resourceType": resource_type,
        "generatedAt": meta.get("generatedAt"),
        "warnings": meta.get("warnings", []),
        "cache": meta.get("cache", {}),
        "progress": progress,
        "snapshotKey": (dataset.get("snapshot") or {}).get("snapshotKey"),
        "snapshotMode": meta.get("snapshotMode"),
        "quality": quality,
    }


def _build_gtfs_import_meta(
    *,
    bundle: Dict[str, Any],
    quality: Dict[str, Any],
    resource_type: str,
) -> Dict[str, Any]:
    meta = bundle.get("meta", {}) if isinstance(bundle, dict) else {}
    return {
        "feedPath": meta.get("feedPath"),
        "agencyName": meta.get("agencyName"),
        "source": "gtfs",
        "resourceType": resource_type,
        "generatedAt": meta.get("generatedAt"),
        "warnings": meta.get("warnings", []),
        "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
        "snapshotMode": meta.get("snapshotMode"),
        "quality": quality,
    }


def _transit_catalog():
    from bff.services import transit_catalog

    return transit_catalog


def _scenario_store():
    from bff.store import scenario_store as store

    return store


def _pick_latest_scenario() -> Optional[Dict[str, Any]]:
    items = _scenario_store().list_scenarios()
    if not items:
        return None
    return sorted(
        items,
        key=lambda item: (
            str(item.get("updatedAt") or ""),
            str(item.get("createdAt") or ""),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )[0]


def _resolve_scenario_id(value: Optional[str], create_name: Optional[str], mode: str) -> str:
    store = _scenario_store()
    if value and value not in {"latest", "new"}:
        store.get_scenario(value)
        return value

    if value == "latest":
        latest = _pick_latest_scenario()
        if latest is None:
            raise RuntimeError("No scenarios found. Use --create-scenario-name to create one.")
        return str(latest["id"])

    name = create_name or "Catalog Sync Scenario"
    scenario = store.create_scenario(
        name=name,
        description="Created by catalog_update_app.py",
        mode=mode,
    )
    return str(scenario["id"])


def _refresh_bundle(
    source: str,
    *,
    operator: str,
    feed_path: str,
    force_refresh: bool,
    ttl_sec: int,
) -> Dict[str, Any]:
    transit_catalog = _transit_catalog()
    _print_header(f"Refresh {source.upper()} catalog")
    if source == "odpt":
        bundle = transit_catalog.refresh_odpt_snapshot(
            operator=operator,
            dump=True,
            force_refresh=force_refresh,
            ttl_sec=ttl_sec,
            progress_callback=_progress_logger,
        )
    else:
        bundle = transit_catalog.refresh_gtfs_snapshot(
            feed_path=feed_path,
            progress_callback=_progress_logger,
        )
    snapshot_key = str(bundle.get("snapshotKey") or bundle.get("snapshot_key") or "")
    print(f"snapshot: {snapshot_key or '-'}")
    loaded = transit_catalog.load_snapshot_bundle(snapshot_key) if snapshot_key else bundle
    artifacts = dict((loaded.get("meta") or {}).get("artifacts") or {})
    if artifacts:
        print(f"artifacts: {json.dumps(artifacts, ensure_ascii=False)}")
    return loaded


def _get_or_load_bundle(
    source: str,
    *,
    operator: str,
    feed_path: str,
    refresh: bool,
    force_refresh: bool,
    ttl_sec: int,
) -> Dict[str, Any]:
    transit_catalog = _transit_catalog()
    if refresh:
        return _refresh_bundle(
            source,
            operator=operator,
            feed_path=feed_path,
            force_refresh=force_refresh,
            ttl_sec=ttl_sec,
        )
    if source == "odpt":
        return transit_catalog.get_or_refresh_odpt_snapshot(
            operator=operator,
            dump=True,
            force_refresh=False,
            ttl_sec=ttl_sec,
        )
    return transit_catalog.get_or_refresh_gtfs_snapshot(feed_path=feed_path)


def _sync_bundle_to_scenario(
    *,
    scenario_id: str,
    source: str,
    bundle: Dict[str, Any],
    operator: str,
    feed_path: str,
    resources: Sequence[str],
    reset_existing: bool,
) -> None:
    store = _scenario_store()
    from bff.services.gtfs_import import (
        summarize_gtfs_routes_import,
        summarize_gtfs_stop_import,
        summarize_gtfs_stop_timetable_import,
        summarize_gtfs_timetable_import,
    )
    from bff.services.odpt_routes import summarize_routes_import
    from bff.services.odpt_stops import summarize_stop_import
    from bff.services.odpt_stop_timetables import summarize_stop_timetable_import
    from bff.services.odpt_timetable import (
        normalize_timetable_row_indexes,
        summarize_timetable_import,
    )

    meta = dict(bundle.get("meta") or {})
    _print_header(f"Sync {source.upper()} bundle -> scenario {scenario_id}")

    if "routes" in resources:
        routes = list(bundle.get("routes") or [])
        if source == "odpt":
            route_meta = {
                "operator": operator,
                "dump": meta.get("effectiveDump", meta.get("dump", True)),
                "requestedDump": True,
                "source": "odpt",
                "generatedAt": meta.get("generatedAt"),
                "warnings": meta.get("warnings", []),
                "cache": meta.get("cache", {}),
                "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
                "snapshotMode": meta.get("snapshotMode"),
                "quality": summarize_routes_import(routes, {"meta": meta}),
            }
        else:
            route_meta = {
                "source": "gtfs",
                "feedPath": meta.get("feedPath") or feed_path,
                "agencyName": meta.get("agencyName"),
                "resourceType": "GTFSRoutePattern",
                "generatedAt": meta.get("generatedAt"),
                "warnings": meta.get("warnings", []),
                "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
                "snapshotMode": meta.get("snapshotMode"),
                "quality": summarize_gtfs_routes_import(routes, {"meta": meta}),
            }
        store.replace_routes_from_source(scenario_id, source, routes, import_meta=route_meta)
        print(f"[sync] routes={len(routes)}")

    if "stops" in resources:
        stops = list(bundle.get("stops") or [])
        if source == "odpt":
            stop_meta = {
                "operator": operator,
                "dump": meta.get("effectiveDump", meta.get("dump", True)),
                "requestedDump": True,
                "source": "odpt",
                "generatedAt": meta.get("generatedAt"),
                "warnings": meta.get("warnings", []),
                "cache": meta.get("cache", {}),
                "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
                "snapshotMode": meta.get("snapshotMode"),
                "quality": summarize_stop_import(stops, {"meta": meta}),
            }
        else:
            stop_meta = {
                "source": "gtfs",
                "feedPath": meta.get("feedPath") or feed_path,
                "agencyName": meta.get("agencyName"),
                "resourceType": "GTFSStop",
                "generatedAt": meta.get("generatedAt"),
                "warnings": meta.get("warnings", []),
                "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
                "snapshotMode": meta.get("snapshotMode"),
                "quality": summarize_gtfs_stop_import(stops, {"meta": meta}),
            }
        store.replace_stops_from_source(scenario_id, source, stops, import_meta=stop_meta)
        print(f"[sync] stops={len(stops)}")

    if "timetable" in resources:
        rows = list(bundle.get("timetable_rows") or [])
        merged_rows = store.upsert_timetable_rows_from_source(
            scenario_id,
            source,
            rows,
            replace_existing_source=reset_existing,
        )
        normalized_rows = normalize_timetable_row_indexes(merged_rows)
        store.set_field(scenario_id, "timetable_rows", normalized_rows, invalidate_dispatch=True)
        source_rows = [row for row in normalized_rows if row.get("source") == source]
        if source == "odpt":
            quality = summarize_timetable_import(
                source_rows,
                {
                    "meta": meta,
                    "stopTimetables": list(bundle.get("stop_timetables") or []),
                },
            )
            timetable_meta = _build_odpt_import_meta(
                dataset=bundle,
                operator=operator,
                dump=True,
                quality=quality,
                progress_key="busTimetables",
                resource_type="BusTimetable",
            )
        else:
            quality = summarize_gtfs_timetable_import(
                source_rows,
                {
                    "meta": meta,
                    "stop_timetable_count": len(list(bundle.get("stop_timetables") or [])),
                },
            )
            timetable_meta = _build_gtfs_import_meta(
                bundle=bundle,
                quality=quality,
                resource_type="GTFSTrip",
            )
        store.set_timetable_import_meta(scenario_id, source, timetable_meta)
        print(f"[sync] timetable_rows={len(source_rows)}")

    if "stop-timetables" in resources:
        items = list(bundle.get("stop_timetables") or [])
        merged_items = store.upsert_stop_timetables_from_source(
            scenario_id,
            source,
            items,
            replace_existing_source=reset_existing,
        )
        source_items = [item for item in merged_items if item.get("source") == source]
        if source == "odpt":
            quality = summarize_stop_timetable_import(source_items, {"meta": meta})
            stop_tt_meta = _build_odpt_import_meta(
                dataset=bundle,
                operator=operator,
                dump=True,
                quality=quality,
                progress_key="stopTimetables",
                resource_type="BusstopPoleTimetable",
            )
        else:
            quality = summarize_gtfs_stop_timetable_import(source_items, bundle)
            stop_tt_meta = _build_gtfs_import_meta(
                bundle=bundle,
                quality=quality,
                resource_type="GTFSStopTimetable",
            )
        store.set_stop_timetable_import_meta(scenario_id, source, stop_tt_meta)
        print(f"[sync] stop_timetables={len(source_items)}")

    if source == "gtfs" and "calendar" in resources:
        for entry in list(bundle.get("calendar_entries") or []):
            store.upsert_calendar_entry(scenario_id, entry)
        for entry in list(bundle.get("calendar_date_entries") or []):
            store.upsert_calendar_date(scenario_id, entry)
        print(
            "[sync] calendar="
            f"{len(list(bundle.get('calendar_entries') or []))}, "
            f"calendar_dates={len(list(bundle.get('calendar_date_entries') or []))}"
        )


def _parse_resources(value: Optional[str]) -> Sequence[str]:
    if not value or value == "all":
        return ALL_RESOURCES
    items = [item.strip() for item in value.split(",") if item.strip()]
    invalid = sorted(set(items) - set(ALL_RESOURCES))
    if invalid:
        raise RuntimeError(f"Unknown resource(s): {', '.join(invalid)}")
    return items


def _cmd_list_scenarios(_: argparse.Namespace) -> int:
    store = _scenario_store()
    _print_header("Scenarios")
    for item in store.list_scenarios():
        print(f"{item['id']}  {item['name']}  updated={item.get('updatedAt')}")
    return 0


def _cmd_list_snapshots(_: argparse.Namespace) -> int:
    transit_catalog = _transit_catalog()
    _print_header("Catalog snapshots")
    for item in transit_catalog.list_snapshots():
        print(
            f"{item['snapshotKey']}  source={item['source']}  "
            f"generated={item.get('generatedAt')}  refreshed={item.get('refreshedAt')}"
        )
    return 0


def _cmd_refresh(args: argparse.Namespace) -> int:
    if args.source == "gtfs-pipeline":
        result: Dict[str, Any] = {}
        try:
            PipelineConfig, run_pipeline = _tokyubus_gtfs_pipeline()
            result = run_pipeline(
                PipelineConfig(
                    source_dir=Path(args.source_dir).resolve(),
                    snapshot_id=args.snapshot_id,
                    gtfs_out_dir=Path(args.feed_path).resolve(),
                    skip_archive=args.skip_archive,
                    skip_gtfs=args.skip_gtfs,
                    skip_features=args.skip_features,
                    profile=args.profile,
                )
            )
            result["pipeline_fallback"] = False
        except ModuleNotFoundError as exc:
            # core package may exclude full data-prep modules; keep built rebuild available.
            result = {
                "pipeline_fallback": True,
                "pipeline_warning": str(exc),
                "message": "tokyubus_gtfs pipeline is unavailable in this package. Running built rebuild only.",
            }
        if not args.skip_built_datasets:
            result["built_datasets"] = _rebuild_tokyu_built_datasets(
                dataset_ids=_parse_dataset_ids(args.built_datasets),
                feed_path=str(Path(args.feed_path).resolve()),
                strict_gtfs_reconciliation=args.strict_gtfs_reconciliation,
                source_dir=str(Path(args.source_dir).resolve()),
            )
        if args.build_gtfs_db:
            result["gtfs_db"] = _build_gtfs_sqlite_catalog(
                dataset_id=args.gtfs_db_dataset_id,
                feed_path=str(Path(args.feed_path).resolve()),
                db_path=args.gtfs_db_path,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.source == "odpt":
        PipelineConfig, run_pipeline = _tokyubus_gtfs_pipeline()

        out_dir = args.out_dir or "./data/catalog-fast"
        fast_args = [
            "fetch-odpt",
            "--out-dir",
            out_dir,
            "--concurrency",
            str(args.concurrency),
        ]
        if args.resume:
            fast_args.append("--resume")
        if args.skip_stop_timetables:
            fast_args.append("--skip-stop-timetables")
        rc = _fast_ingest().main(fast_args)
        if rc != 0 or args.fetch_only:
            return rc
        result = run_pipeline(
            PipelineConfig(
                source_dir=Path(out_dir).resolve(),
                snapshot_id=args.snapshot_id,
                gtfs_out_dir=Path(args.feed_path).resolve(),
                skip_archive=args.skip_archive,
                skip_gtfs=args.skip_gtfs,
                skip_features=args.skip_features,
                profile=args.profile,
            )
        )
        if not args.skip_built_datasets:
            result["built_datasets"] = _rebuild_tokyu_built_datasets(
                dataset_ids=_parse_dataset_ids(args.built_datasets),
                feed_path=str(Path(args.feed_path).resolve()),
                strict_gtfs_reconciliation=args.strict_gtfs_reconciliation,
                source_dir=str(Path(out_dir).resolve()),
            )
        if args.build_gtfs_db:
            result["gtfs_db"] = _build_gtfs_sqlite_catalog(
                dataset_id=args.gtfs_db_dataset_id,
                feed_path=str(Path(args.feed_path).resolve()),
                db_path=args.gtfs_db_path,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        print("note: research runtime uses bff/ as the official backend; backend_legacy/ is legacy")
        return 0
    if getattr(args, "fast_path", False):
        if args.source != "odpt":
            raise RuntimeError("--fast-path refresh is currently supported for ODPT only")
    _get_or_load_bundle(
        args.source,
        operator=args.operator,
        feed_path=args.feed_path,
        refresh=True,
        force_refresh=args.force_refresh,
        ttl_sec=args.ttl_sec,
    )
    if args.build_gtfs_db:
        payload = _build_gtfs_sqlite_catalog(
            dataset_id=args.gtfs_db_dataset_id,
            feed_path=str(Path(args.feed_path).resolve()),
            db_path=args.gtfs_db_path,
        )
        print(json.dumps({"gtfs_db": payload}, ensure_ascii=False, indent=2))
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    if getattr(args, "fast_path", False):
        if args.source == "gtfs":
            fast_args = [
                "sync-gtfs",
                "--scenario",
                args.scenario,
                "--resources",
                args.resources,
                "--feed-path",
                args.feed_path,
                "--ttl-sec",
                str(args.ttl_sec),
            ]
            if args.refresh:
                fast_args.append("--refresh")
            if args.force_refresh:
                fast_args.append("--force-refresh")
            if args.keep_existing_source:
                fast_args.append("--keep-existing-source")
            return _fast_ingest().main(fast_args)

        out_dir = args.out_dir or "./data/catalog-fast"
        started = time.perf_counter()
        fast_args = [
            "fetch-odpt",
            "--out-dir",
            out_dir,
            "--concurrency",
            str(args.concurrency),
            "--build-bundle",
        ]
        if args.resume:
            fast_args.append("--resume")
        if args.skip_stop_timetables:
            fast_args.append("--skip-stop-timetables")
        rc = _fast_ingest().main(fast_args)
        if rc != 0:
            return rc
        bundle_path = _fast_ingest().Path(out_dir).resolve() / "bundle.json"
        bundle = _fast_ingest()._json_load(bundle_path)
        scenario_id = _resolve_scenario_id(args.scenario, args.create_scenario_name, args.mode)
        resources = _parse_resources(args.resources)
        _sync_bundle_to_scenario(
            scenario_id=scenario_id,
            source="odpt",
            bundle=bundle,
            operator=args.operator,
            feed_path=args.feed_path,
            resources=resources,
            reset_existing=not args.keep_existing_source,
        )
        print(f"[done] scenario={scenario_id} elapsed={time.perf_counter() - started:.2f}s")
        return 0

    scenario_id = _resolve_scenario_id(args.scenario, args.create_scenario_name, args.mode)
    resources = _parse_resources(args.resources)
    bundle = _get_or_load_bundle(
      args.source,
      operator=args.operator,
      feed_path=args.feed_path,
      refresh=args.refresh,
      force_refresh=args.force_refresh,
      ttl_sec=args.ttl_sec,
    )
    _sync_bundle_to_scenario(
        scenario_id=scenario_id,
        source=args.source,
        bundle=bundle,
        operator=args.operator,
        feed_path=args.feed_path,
        resources=resources,
        reset_existing=not args.keep_existing_source,
    )
    print(f"[done] scenario={scenario_id}")
    return 0


def _run_interactive() -> int:
    print("catalog_update_app.py")
    print("1) list scenarios")
    print("2) list snapshots")
    print("3) refresh odpt")
    print("4) refresh gtfs")
    print("5) sync odpt -> latest scenario")
    print("6) sync gtfs -> latest scenario")
    choice = input("select> ").strip()
    if choice == "1":
        return _cmd_list_scenarios(argparse.Namespace())
    if choice == "2":
        return _cmd_list_snapshots(argparse.Namespace())
    if choice == "3":
        return _cmd_refresh(
            argparse.Namespace(
                source="odpt",
                operator=DEFAULT_OPERATOR,
                feed_path=DEFAULT_GTFS_FEED_PATH,
                source_dir=DEFAULT_TOKYUBUS_PIPELINE_SOURCE_DIR,
                snapshot_id=None,
                force_refresh=True,
                ttl_sec=3600,
                skip_archive=False,
                skip_gtfs=False,
                skip_features=False,
                fast_path=False,
                fetch_only=False,
                profile="fast",
                out_dir="./data/catalog-fast",
                concurrency=32,
                resume=False,
                skip_stop_timetables=False,
                built_datasets="tokyu_core,tokyu_full",
                skip_built_datasets=False,
                strict_gtfs_reconciliation=False,
                build_gtfs_db=False,
                gtfs_db_dataset_id="tokyu_full",
                gtfs_db_path="data/tokyu_gtfs.sqlite",
            )
        )
    if choice == "4":
        return _cmd_refresh(
            argparse.Namespace(
                source="gtfs",
                operator=DEFAULT_OPERATOR,
                feed_path=DEFAULT_GTFS_FEED_PATH,
                source_dir=DEFAULT_TOKYUBUS_PIPELINE_SOURCE_DIR,
                snapshot_id=None,
                force_refresh=True,
                ttl_sec=3600,
                skip_archive=False,
                skip_gtfs=False,
                skip_features=False,
                fast_path=False,
                fetch_only=False,
                profile="fast",
                out_dir="./data/catalog-fast",
                concurrency=32,
                resume=False,
                skip_stop_timetables=False,
                built_datasets="tokyu_core,tokyu_full",
                skip_built_datasets=False,
                strict_gtfs_reconciliation=False,
                build_gtfs_db=False,
                gtfs_db_dataset_id="tokyu_full",
                gtfs_db_path="data/tokyu_gtfs.sqlite",
            )
        )
    if choice == "5":
        return _cmd_sync(
            argparse.Namespace(
                source="odpt",
                operator=DEFAULT_OPERATOR,
                feed_path=DEFAULT_GTFS_FEED_PATH,
                scenario="latest",
                create_scenario_name=None,
                mode="mode_B_resource_assignment",
                refresh=True,
                force_refresh=True,
                ttl_sec=3600,
                resources="all",
                keep_existing_source=False,
            )
        )
    if choice == "6":
        return _cmd_sync(
            argparse.Namespace(
                source="gtfs",
                operator=DEFAULT_OPERATOR,
                feed_path=DEFAULT_GTFS_FEED_PATH,
                scenario="latest",
                create_scenario_name=None,
                mode="mode_B_resource_assignment",
                refresh=True,
                force_refresh=True,
                ttl_sec=3600,
                resources="all",
                keep_existing_source=False,
            )
        )
    print("invalid choice")
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone catalog/scenario updater for ODPT and GTFS.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-scenarios", help="List available scenarios")
    subparsers.add_parser("list-snapshots", help="List catalog snapshots")

    refresh_parser = subparsers.add_parser("refresh", help="Refresh catalog snapshot only")
    refresh_parser.add_argument("source", choices=["odpt", "gtfs", "gtfs-pipeline"])
    refresh_parser.add_argument("--operator", default=DEFAULT_OPERATOR)
    refresh_parser.add_argument("--feed-path", default=DEFAULT_GTFS_FEED_PATH)
    refresh_parser.add_argument("--source-dir", default=DEFAULT_TOKYUBUS_PIPELINE_SOURCE_DIR)
    refresh_parser.add_argument("--snapshot-id")
    refresh_parser.add_argument("--ttl-sec", type=int, default=3600)
    refresh_parser.add_argument("--force-refresh", action="store_true")
    refresh_parser.add_argument("--skip-archive", action="store_true")
    refresh_parser.add_argument("--skip-gtfs", action="store_true")
    refresh_parser.add_argument("--skip-features", action="store_true")
    refresh_parser.add_argument("--fast-path", action="store_true")
    refresh_parser.add_argument("--out-dir", default="./data/catalog-fast")
    refresh_parser.add_argument("--concurrency", type=int, default=32)
    refresh_parser.add_argument("--resume", action="store_true")
    refresh_parser.add_argument("--skip-stop-timetables", action="store_true")
    refresh_parser.add_argument("--fetch-only", action="store_true")
    refresh_parser.add_argument("--profile", choices=["fast", "full"], default="fast")
    refresh_parser.add_argument("--built-datasets", default="tokyu_core,tokyu_full")
    refresh_parser.add_argument("--skip-built-datasets", action="store_true")
    refresh_parser.add_argument("--strict-gtfs-reconciliation", action="store_true")
    refresh_parser.add_argument("--build-gtfs-db", action="store_true")
    refresh_parser.add_argument("--gtfs-db-dataset-id", default="tokyu_full")
    refresh_parser.add_argument("--gtfs-db-path", default="data/tokyu_gtfs.sqlite")

    sync_parser = subparsers.add_parser("sync", help="Refresh catalog and sync data into a scenario")
    sync_parser.add_argument("source", choices=["odpt", "gtfs"])
    sync_parser.add_argument("--scenario", default="latest")
    sync_parser.add_argument("--create-scenario-name")
    sync_parser.add_argument("--mode", default="mode_B_resource_assignment")
    sync_parser.add_argument("--operator", default=DEFAULT_OPERATOR)
    sync_parser.add_argument("--feed-path", default=DEFAULT_GTFS_FEED_PATH)
    sync_parser.add_argument("--resources", default="all")
    sync_parser.add_argument("--ttl-sec", type=int, default=3600)
    sync_parser.add_argument("--refresh", action="store_true")
    sync_parser.add_argument("--force-refresh", action="store_true")
    sync_parser.add_argument("--keep-existing-source", action="store_true")
    sync_parser.add_argument("--fast-path", action="store_true")
    sync_parser.add_argument("--out-dir", default="./data/catalog-fast")
    sync_parser.add_argument("--concurrency", type=int, default=32)
    sync_parser.add_argument("--resume", action="store_true")
    sync_parser.add_argument("--skip-stop-timetables", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        return _run_interactive()
    if args.command == "list-scenarios":
        return _cmd_list_scenarios(args)
    if args.command == "list-snapshots":
        return _cmd_list_snapshots(args)
    if args.command == "refresh":
        return _cmd_refresh(args)
    if args.command == "sync":
        return _cmd_sync(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise
