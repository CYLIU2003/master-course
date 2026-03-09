#!/usr/bin/env python3
"""
catalog_update_app.py

Standalone data-update app for ODPT / GTFS refresh and scenario sync.

This script is intentionally separate from the main frontend/BFF runtime so
heavy public-data refresh work can be run on demand.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_OPERATOR = "odpt.Operator:TokyuBus"
DEFAULT_GTFS_FEED_PATH = "GTFS/ToeiBus-GTFS"
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
    return transit_catalog.load_snapshot_bundle(snapshot_key) if snapshot_key else bundle


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
    if getattr(args, "fast_path", False):
        if args.source != "odpt":
            raise RuntimeError("--fast-path refresh is currently supported for ODPT only")
        out_dir = args.out_dir or "./data/catalog-fast"
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
        return _fast_ingest().main(fast_args)
    _get_or_load_bundle(
        args.source,
        operator=args.operator,
        feed_path=args.feed_path,
        refresh=True,
        force_refresh=args.force_refresh,
        ttl_sec=args.ttl_sec,
    )
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
                force_refresh=True,
                ttl_sec=3600,
            )
        )
    if choice == "4":
        return _cmd_refresh(
            argparse.Namespace(
                source="gtfs",
                operator=DEFAULT_OPERATOR,
                feed_path=DEFAULT_GTFS_FEED_PATH,
                force_refresh=True,
                ttl_sec=3600,
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
    refresh_parser.add_argument("source", choices=["odpt", "gtfs"])
    refresh_parser.add_argument("--operator", default=DEFAULT_OPERATOR)
    refresh_parser.add_argument("--feed-path", default=DEFAULT_GTFS_FEED_PATH)
    refresh_parser.add_argument("--ttl-sec", type=int, default=3600)
    refresh_parser.add_argument("--force-refresh", action="store_true")
    refresh_parser.add_argument("--fast-path", action="store_true")
    refresh_parser.add_argument("--out-dir", default="./data/catalog-fast")
    refresh_parser.add_argument("--concurrency", type=int, default=32)
    refresh_parser.add_argument("--resume", action="store_true")
    refresh_parser.add_argument("--skip-stop-timetables", action="store_true")

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
