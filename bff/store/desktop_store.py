"""Bounded read projections for the desktop UI; never changes research inputs."""

from __future__ import annotations

import io
import json
import math
import re
import sqlite3
import unicodedata
from contextlib import closing, contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO

import ijson

from bff.store import scenario_store, trip_store
from bff.store.desktop_json import LegacyResultReader
from bff.store.output_paths import outputs_root, project_root
from src.geo import haversine_km

MASTER_TABLES = frozenset({"routes", "depots", "vehicles", "stops", "chargers", "vehicle_templates"})
ARTIFACT_TABLES = frozenset({"timetable_rows", "trips", "duties", "blocks"})
SCENARIO_ROUTE_GROUPS = frozenset({"shibu24", "shibu21_24", "shibu21_23", "other"})
SCENARIO_PERIOD_KINDS = frozenset({"all", "reusable", "dated_history"})
RESULT_PATHS = (
    "status",
    "solver_status",
    "feasible",
    "objective_value",
    "cost_breakdown",
    "mip_gap",
    "solve_time_seconds",
    "summary.vehicle_count_used",
    "summary.trip_count_served",
    "summary.trip_count_unserved",
    "simulation_summary.total_co2_kg",
    "simulation_summary.total_fuel_cost",
    "simulation_summary.peak_demand_kw",
    "solution_validity",
    "result_class",
    "research_kpi_eligible",
    "prepared_input_id",
    "scenario_hash",
    "scope_hash",
    "final_accounting_source",
    "final_accounting_total_cost_jpy",
    "solver_metadata.research_git_provenance",
    "metadata.research_acceptance_status",
    "metadata.research_acceptance_checks",
    "metadata.physical_schedule_validation",
    "metadata.accounting_summary",
    "metadata.git_commit",
    "metadata.git_sha",
    "metadata.mip_gap",
    "metadata.fallback_used",
    "metadata.post_solve_repair_used",
    "metadata.rolling_hourly_chain_summary",
    "metadata.claim_scope",
    "total_operating_cost", "total_energy_cost", "total_demand_charge",
    "total_degradation_cost", "total_fuel_cost", "total_co2_kg",
    "total_pv_kwh", "total_grid_kwh", "peak_demand_kw", "served_task_ratio",
    "electricity_cost_basis", "electricity_cost_provisional_jpy",
    "electricity_cost_charged_jpy", "feasibility_report",
)


def _context(scenario_id: str) -> tuple[dict[str, Any], dict[str, str]]:
    # Reuse the scenario store's ref normalization (including moved workspaces).
    return scenario_store.get_desktop_context(scenario_id)


def _read_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


@lru_cache(maxsize=256)
def _metadata(path: str, modified_ns: int, size: int) -> dict[str, Any]:
    del modified_ns, size  # Cache identity includes atomic replacements.
    with open(path, "rb") as source:
        meta = next(ijson.items(source, "meta"), {})
    if (
        not isinstance(meta, dict)
        or not isinstance(meta.get("id"), str)
        or not isinstance(meta.get("name"), str)
    ):
        raise ValueError("Invalid scenario metadata")
    result = {
        key: meta.get(key)
        for key in ("id", "name", "description", "status", "updatedAt", "operatorId")
    }
    result["routeGroup"] = scenario_route_group(str(meta["name"]))
    result["runInstance"] = bool(meta.get("run_instance", False))
    result["parentScenarioId"] = meta.get("base_scenario_id")
    return result


def scenario_route_group(name: str) -> str:
    """Conservative display-only grouping based on a saved scenario's name.

    A name does not prove the underlying route scope. Unnamed or ambiguous
    scenarios remain in ``other``; optimization never consumes this label.
    """
    normalized = unicodedata.normalize("NFKC", name).casefold()
    compact = re.sub(r"\s+", "", normalized)
    if re.search(r"(?:渋|shibu)21[-~](?:(?:渋|shibu)?22[-~])?(?:渋|shibu)?24", compact):
        return "shibu21_24"
    if re.search(r"(?:渋|shibu)21[-~](?:(?:渋|shibu)?22[-~])?(?:渋|shibu)?23", compact):
        return "shibu21_23"
    if re.search(r"(?:渋|shibu)24(?!\d)", compact):
        return "shibu24"
    if re.search(r"(?:渋|shibu)2[123](?!\d)", compact):
        return "shibu21_23"
    return "other"


def scenario_period_kind(name: str) -> str:
    """Classify legacy date-named copies for display; never infer solver scope."""
    normalized = unicodedata.normalize("NFKC", name)
    if (re.search(r"\d{4}年\d{1,2}月代表週\s+\d{4}-\d{2}-\d{2}", normalized)
            or re.search(r"7日入力候補\s+\d{4}-\d{2}-\d{2}", normalized)):
        return "dated_history"
    return "reusable"


def scenario_page(query: str, offset: int, limit: int, route_group: str = "all",
                  period_kind: str = "all") -> dict[str, Any]:
    if route_group != "all" and route_group not in SCENARIO_ROUTE_GROUPS:
        raise ValueError("Unknown scenario route group")
    if period_kind not in SCENARIO_PERIOD_KINDS:
        raise ValueError("Unknown scenario period kind")
    items, errors = [], []
    for path in scenario_store.scenario_metadata_paths():
        try:
            stat = path.stat()
            meta = _metadata(str(path), stat.st_mtime_ns, stat.st_size)
            if (
                meta.get("id")
                and query.casefold() in str(meta.get("name") or "").casefold()
                and (route_group == "all" or meta["routeGroup"] == route_group)
                and (period_kind == "all" or
                     ("dated_history" if meta.get("runInstance") else scenario_period_kind(meta["name"])) == period_kind)
            ):
                items.append(meta)
        except (OSError, ValueError, ijson.JSONError) as exc:
            errors.append(f"{path.stem}: {type(exc).__name__}")
    items.sort(
        key=lambda row: (str(row.get("updatedAt") or ""), str(row["id"])), reverse=True
    )
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "offset": offset,
        "limit": limit,
        "warnings": errors[:20],
    }


def collection(scenario_id: str, name: str) -> Any:
    meta, refs = _context(scenario_id)
    path = Path(refs["masterData"])
    if path.exists():
        with closing(_read_connection(path)) as conn:
            row = conn.execute(
                "SELECT payload_json FROM collections WHERE name = ?", (name,)
            ).fetchone()
        if row is not None:
            return json.loads(row[0])
    return meta.get(name)


@lru_cache(maxsize=2)
def _catalog_stop_index(path: str, modified_ns: int) -> dict[str, dict[str, Any]]:
    del modified_ns
    with open(path, encoding="utf-8") as source:
        return {
            str(stop["id"]): stop
            for line in source
            if (stop := json.loads(line)).get("id")
        }


def _display_stop_catalog() -> dict[str, dict[str, Any]]:
    path = project_root() / "data" / "catalog-fast" / "normalized" / "stops.jsonl"
    if not path.is_file():
        return {}
    return _catalog_stop_index(str(path), path.stat().st_mtime_ns)


def _project_route_catalog(
    depots: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    stops: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    *,
    source_label: str,
    supplemental_stops: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    depot_names = {str(row["id"]): str(row.get("name") or row["id"]) for row in depots if row.get("id")}
    assigned = {str(row["routeId"]): str(row["depotId"]) for row in assignments if row.get("routeId") and row.get("depotId")}
    stop_by_id = {str(row["id"]): row for row in stops if row.get("id")}
    items: list[dict[str, Any]] = []
    for route in routes:
        route_id = str(route.get("id") or "")
        if not route_id:
            continue
        depot_ids = [str(value) for value in route.get("depotIds", []) if str(value) in depot_names] if isinstance(route.get("depotIds"), list) else []
        primary = assigned.get(route_id) or str(route.get("depotId") or route.get("depot_id") or "")
        if primary in depot_names and primary not in depot_ids:
            depot_ids.insert(0, primary)
        stop_ids = route.get("stopSequence")
        if not isinstance(stop_ids, list):
            stop_ids = []
        stop_details = []
        distance = 0.0
        complete = len(stop_ids) >= 2
        previous = None
        used_supplement = False
        for stop_id in stop_ids:
            stop = stop_by_id.get(str(stop_id), {})
            lat, lon = stop.get("lat"), stop.get("lon")
            coordinate_source = source_label
            if (lat is None or lon is None) and str(stop_id).startswith("odpt.BusstopPole:") and str(route.get("source") or "").lower() in {"odpt", "gtfs"}:
                supplement = supplemental_stops.get(str(stop_id), {})
                if supplement.get("lat") is not None and supplement.get("lon") is not None:
                    stop = supplement
                    lat, lon = stop["lat"], stop["lon"]
                    coordinate_source = "catalog_fast_display_only"
                    used_supplement = True
            coordinate = None
            try:
                if lat is not None and lon is not None:
                    coordinate = (float(lat), float(lon))
                    if not (math.isfinite(coordinate[0]) and math.isfinite(coordinate[1]) and -90 <= coordinate[0] <= 90 and -180 <= coordinate[1] <= 180):
                        coordinate = None
            except (TypeError, ValueError):
                pass
            if coordinate is None:
                complete = False
            if previous is not None:
                if coordinate is None or previous is False:
                    complete = False
                else:
                    distance += haversine_km(*previous, *coordinate)
            previous = coordinate if coordinate is not None else False
            stop_details.append({
                "id": str(stop_id), "name": str(stop.get("name") or stop_id),
                "lat": coordinate[0] if coordinate else None,
                "lon": coordinate[1] if coordinate else None,
                "coordinateSource": coordinate_source if coordinate else "unresolved",
            })
        items.append({
            "id": route_id,
            "name": str(route.get("name") or route.get("routeLabel") or route_id),
            "routeCode": str(route.get("routeFamilyCode") or route.get("routeCode") or ""),
            "routeVariantType": str(route.get("routeVariantTypeManual") or route.get("routeVariantType") or "unknown"),
            "direction": str(route.get("canonicalDirectionManual") or route.get("canonicalDirection") or route.get("direction") or "unknown"),
            "startStop": str(route.get("startStop") or (stop_details[0]["name"] if stop_details else "")),
            "endStop": str(route.get("endStop") or (stop_details[-1]["name"] if stop_details else "")),
            "depotIds": depot_ids,
            "stopCount": len(stop_details),
            "stops": stop_details,
            "distanceKm": round(distance, 6) if complete and distance > 0 else None,
            "storedDistanceKm": route.get("distanceKm"),
            "distanceSource": ("catalog_fast_stop_sequence_haversine_display_only" if used_supplement else f"{source_label}_stop_sequence_haversine") if complete and distance > 0 else "unresolved_stop_coordinates",
            "tripCount": route.get("tripCount"),
            "tripCountsByDayType": route.get("tripCountsByDayType"),
            "firstDepartureByDayType": route.get("firstDepartureByDayType"),
            "lastArrivalByDayType": route.get("lastArrivalByDayType"),
            "odptPatternId": route.get("odptPatternId"),
            "classificationConfidence": route.get("classificationConfidence"),
            "classificationSource": route.get("classificationSource"),
            "source": route.get("source"),
        })
    return {
        "depots": [{"id": depot_id, "name": name} for depot_id, name in depot_names.items()],
        "routes": items,
    }


def route_catalog(scenario_id: str) -> dict[str, Any]:
    """Read-only scenario pattern projection; never changes prepared inputs."""
    return _project_route_catalog(
        collection(scenario_id, "depots") or [],
        collection(scenario_id, "routes") or [],
        collection(scenario_id, "stops") or [],
        collection(scenario_id, "route_depot_assignments") or [],
        source_label="scenario",
        supplemental_stops=_display_stop_catalog(),
    )


def odpt_route_catalog() -> dict[str, Any]:
    """Browse the frozen ODPT catalog independently of scenario scope."""
    root = project_root()
    routes_path = root / "data" / "catalog-fast" / "tokyu_bus_data" / "routes.jsonl"
    depot_path = root / "data" / "seed" / "tokyu" / "depots.json"
    summary_path = root / "data" / "catalog-fast" / "tokyu_bus_data" / "network_summary.json"
    if not routes_path.is_file() or not depot_path.is_file():
        raise FileNotFoundError("Frozen ODPT route catalog is unavailable")
    with routes_path.open(encoding="utf-8") as source:
        routes = [json.loads(line) for line in source if line.strip()]
    with depot_path.open(encoding="utf-8") as source:
        depots = json.load(source)["depots"]
    stops = _display_stop_catalog()
    result = _project_route_catalog(
        depots, routes, list(stops.values()), [],
        source_label="odpt_catalog",
        supplemental_stops={},
    )
    if summary_path.is_file():
        with summary_path.open(encoding="utf-8") as source:
            summary = json.load(source)
        result["builtAt"] = summary.get("generatedAt")
        result["sourceSnapshotId"] = summary.get("sourceSnapshotId")
    reference_path = root / "data" / "reference" / "tokyu_route_depot_reference_20260925.json"
    if reference_path.is_file():
        with reference_path.open(encoding="utf-8") as source:
            reference = json.load(source)
        if result.get("sourceSnapshotId") != reference["sourceSnapshotId"]:
            result["officialReferenceStatus"] = "snapshot_mismatch"
            return result
        depot_ids = {depot["id"] for depot in result["depots"]}
        by_code: dict[str, dict[str, str]] = {}
        for group in reference["groups"]:
            if group["depotId"] not in depot_ids:
                raise ValueError(f"Unknown official reference depot: {group['depotId']}")
            for code in group["routeCodes"]:
                if code in by_code:
                    raise ValueError(f"Duplicate official reference route code: {code}")
                by_code[code] = {
                    "depotId": group["depotId"],
                    "sourceUrl": group["sourceUrl"],
                    "sourceDate": group["sourceDate"],
                }
        unresolved_by_code = {row["routeCode"]: row for row in reference.get("unresolvedEvidence", [])}
        notice_by_code = {row["routeCode"]: row for row in reference.get("serviceNotices", [])}
        for route in result["routes"]:
            if not route["depotIds"] and route["routeCode"] in by_code:
                route["officialDepotReference"] = by_code[route["routeCode"]]
            if route["routeCode"] in unresolved_by_code:
                route["officialDepotAmbiguity"] = unresolved_by_code[route["routeCode"]]
            if route["routeCode"] in notice_by_code:
                route["officialServiceNotice"] = notice_by_code[route["routeCode"]]
        result["officialReferenceCapturedAt"] = reference["capturedAt"]
    return result


def _indexed_timetable_page(
    path: Path, offset: int, limit: int, service_id: str | None
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with closing(_read_connection(path)) as conn:
        conn.execute("BEGIN")
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'timetable_rows'"
            ).fetchone()
            is None
        ):
            return None
        visible = trip_store.TIMETABLE_VISIBLE_FILTER
        condition = visible + (" AND service_id = ?" if service_id else "")
        params = [service_id] if service_id else []
        total = conn.execute(
            "SELECT COUNT(*) FROM timetable_rows WHERE " + condition, params
        ).fetchone()[0]
        if (
            not total
            and conn.execute(
                "SELECT 1 FROM timetable_rows WHERE " + visible + " LIMIT 1"
            ).fetchone()
            is None
        ):
            return None
        rows = conn.execute(
            "SELECT payload_json FROM timetable_rows WHERE "
            + condition
            + " ORDER BY row_index LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return {
        "items": [json.loads(row[0]) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def table_page(
    scenario_id: str, name: str, offset: int, limit: int, service_id: str | None = None
) -> dict[str, Any]:
    meta, refs = _context(scenario_id)
    if name == "timetable_rows":
        indexed = _indexed_timetable_page(
            Path(refs["artifactStore"]), offset, limit, service_id
        )
        if indexed is not None:
            return indexed
        total = scenario_store.count_timetable_rows(scenario_id, service_id=service_id)
        items = scenario_store.page_timetable_rows(
            scenario_id, offset=offset, limit=limit, service_id=service_id
        )
    elif name in ARTIFACT_TABLES:
        total = scenario_store.count_field_rows(scenario_id, name)
        items = scenario_store.page_field_rows(
            scenario_id, name, offset=offset, limit=limit
        )
    elif name in MASTER_TABLES:
        path = Path(refs["masterData"])
        if path.exists():
            with closing(_read_connection(path)) as conn:
                total_row = conn.execute(
                    "SELECT json_array_length(payload_json) FROM collections WHERE name = ?",
                    (name,),
                ).fetchone()
                total = int(total_row[0] or 0) if total_row else 0
                rows = conn.execute(
                    "SELECT j.value FROM collections c, json_each(c.payload_json) j WHERE c.name = ? ORDER BY CAST(j.key AS INTEGER) LIMIT ? OFFSET ?",
                    (name, limit, offset),
                ).fetchall()
                items = [json.loads(row[0]) for row in rows]
        else:
            rows = meta.get(name) or []
            total, items = len(rows), rows[offset : offset + limit]
    else:
        raise ValueError("Unsupported desktop table")
    return {"items": items, "total": total, "offset": offset, "limit": limit}


def _stream_projection(source: BinaryIO) -> dict[str, Any]:
    # Event projection skips large trajectories/allocations in constant parser memory.
    from ijson.common import ObjectBuilder

    result: dict[str, Any] = {}
    builder = None
    root = ""
    depth = 0
    projected_events = 0
    for prefix, event, value in ijson.parse(
        io.BufferedReader(LegacyResultReader(source)), use_float=True
    ):
        if builder is not None:
            projected_events += 1
            if projected_events > 10_000:
                raise ValueError(
                    "Result summary exceeds the desktop bound; inspect the saved result artifact"
                )
            builder.event(event, value)
            depth += int(event in {"start_map", "start_array"}) - int(
                event in {"end_map", "end_array"}
            )
            if depth == 0:
                result[root] = builder.value
                builder = None
        elif prefix in RESULT_PATHS:
            if event in {"start_map", "start_array"}:
                builder, root, depth = ObjectBuilder(), prefix, 1
                builder.event(event, value)
            elif event in {"string", "number", "boolean", "null"}:
                result[prefix] = value
    return result


def _json_projection(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        return _stream_projection(source)


@lru_cache(maxsize=32)
def _cached_projection(
    path: str, modified_ns: int, size: int, sqlite: bool
) -> dict[str, Any] | None:
    del modified_ns, size
    if not sqlite:
        return _json_projection(Path(path))
    with closing(_read_connection(Path(path))) as conn:
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'scalar_artifacts'"
            ).fetchone()
            is None
        ):
            return None
        row = conn.execute(
            "SELECT rowid FROM scalar_artifacts WHERE name = 'optimization_result'"
        ).fetchone()
        if row is None:
            return None
        # TEXT blobs expose UTF-8 bytes too. No Python allocation of the full
        # solver JSON, and no repeated SQLite JSON extraction of large values.
        with conn.blobopen(
            "scalar_artifacts", "payload_json", row[0], readonly=True
        ) as source:
            return _stream_projection(source)


def result_summary(scenario_id: str) -> dict[str, Any]:
    _, refs = _context(scenario_id)
    path = Path(refs["artifactStore"])
    if path.exists():
        stat = path.stat()
        result = _cached_projection(str(path), stat.st_mtime_ns, stat.st_size, True)
        if result:
            return {
                "available": True,
                "source": "optimization_result",
                "values": result,
            }
    json_path = Path(refs["optimizationResult"])
    if json_path.exists():
        stat = json_path.stat()
        result = _cached_projection(
            str(json_path), stat.st_mtime_ns, stat.st_size, False
        )
        if result:
            return {
                "available": True,
                "source": "optimization_result",
                "values": result,
            }
    return {"available": False, "source": None, "values": {}}


RESULT_SERIES = frozenset({
    "vehicle_soc_kwh_by_vehicle_slot", "bess_soc_kwh_by_depot_slot",
    "grid_to_bus_kwh_by_depot_slot", "pv_to_bus_kwh_by_depot_slot",
    "bess_to_bus_kwh_by_depot_slot", "pv_to_bess_kwh_by_depot_slot",
    "grid_to_bess_kwh_by_depot_slot", "pv_curtail_kwh_by_depot_slot",
})
RESULT_ROWS = frozenset({"charging_schedule", "vehicle_cost_ledger", "daily_cost_ledger"})


class MissingResult(ValueError):
    """The scenario has no persisted result of the requested kind."""


@contextmanager
def result_source(scenario_id: str, artifact: str = "optimization_result"):
    """Open the persisted result without decoding its complete JSON document."""
    _, refs = _context(scenario_id)
    db_path = Path(refs["artifactStore"])
    if db_path.exists():
        with closing(_read_connection(db_path)) as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='scalar_artifacts'").fetchone()
            row = conn.execute("SELECT rowid FROM scalar_artifacts WHERE name=?", (artifact,)).fetchone() if exists else None
            if row:
                with conn.blobopen("scalar_artifacts", "payload_json", row[0], readonly=True) as source:
                    yield io.BufferedReader(LegacyResultReader(source))
                return
    path = Path(refs["simulationResult" if artifact == "simulation_result" else "optimizationResult"])
    if not path.is_file():
        raise MissingResult("保存された結果がありません。")
    with path.open("rb") as source:
        yield io.BufferedReader(LegacyResultReader(source))


def simulation_summary(scenario_id: str) -> dict[str, Any]:
    try:
        with result_source(scenario_id, "simulation_result") as source:
            values = _stream_projection(source)
    except MissingResult:
        values = {}
    return {"available": bool(values), "source": "simulation_result" if values else None,
            "values": values}


def result_page(scenario_id: str, name: str, owner: str, offset: int, limit: int) -> dict[str, Any]:
    if name == "vehicle_gantt_rows":
        return timeline_page(scenario_id, owner, offset, limit)
    if name not in RESULT_SERIES | RESULT_ROWS:
        raise ValueError("Unsupported result data")
    root = "canonical_solver_result." + name
    items, owners, total = [], [], 0
    with result_source(scenario_id) as source:
        if name in RESULT_ROWS:
            for row in ijson.items(source, root + ".item", use_float=True):
                if owner and str(row.get("vehicle_id", "")) != owner:
                    continue
                if offset <= total < offset + limit:
                    items.append(row)
                total += 1
        else:
            for prefix, event, value in ijson.parse(source, use_float=True):
                if prefix == root and event == "map_key" and len(owners) < 250:
                    owners.append(str(value))
                if not owner or not prefix.startswith(root + "." + owner + ".") or event not in {"number", "null", "string"}:
                    continue
                slot = prefix[len(root + "." + owner + "."):]
                if not slot.isdigit():
                    continue
                if offset <= total < offset + limit:
                    items.append({"slot_index": int(slot), "value": value, "owner": owner})
                total += 1
    return {"items": items, "total": total, "offset": offset, "limit": limit,
            "owners": owners, "source": "optimization_result.canonical_solver_result", "scope": "saved_solver_plan"}


def result_directory(scenario_id: str) -> Path | None:
    with result_source(scenario_id) as source:
        directory = next(ijson.items(source, "audit.output_dir"), None)
    if not isinstance(directory, str) or not directory:
        return None
    path = Path(directory)
    if not path.is_absolute():
        path = project_root() / path
    path = path.resolve()
    if not path.is_relative_to(outputs_root().resolve()):
        raise ValueError("結果の出力先が許可されたoutputフォルダー外です。")
    return path


RESULT_FILE_EXTENSIONS = frozenset({".csv", ".json", ".xlsx", ".png", ".pdf", ".md"})


def result_file(scenario_id: str, name: str) -> Path:
    directory = result_directory(scenario_id)
    if directory is None:
        raise MissingResult("結果の出力フォルダーが保存されていません。")
    path = (directory / name).resolve()
    if not path.is_relative_to(directory) or path.suffix.lower() not in RESULT_FILE_EXTENSIONS:
        raise ValueError("許可された結果ファイルを指定してください。")
    if not path.is_file() or path.stat().st_size > 100_000_000:
        raise ValueError("ファイルが存在しないか、画面から取得できる100 MBの上限を超えています。")
    return path


def result_files(scenario_id: str) -> dict[str, Any]:
    directory = result_directory(scenario_id)
    result = {"directory": str(directory) if directory else None, "items": [], "truncated": False}
    if directory is None:
        return result
    for folder in (directory, directory / "graph"):
        if not folder.is_dir() or not folder.resolve().is_relative_to(directory):
            continue
        for path in folder.iterdir():
            if not path.is_file() or path.suffix.lower() not in RESULT_FILE_EXTENSIONS or not path.resolve().is_relative_to(directory):
                continue
            if len(result["items"]) == 250:
                result["truncated"] = True
                return result
            result["items"].append({"name": path.relative_to(directory).as_posix(), "bytes": path.stat().st_size})
    return result


def timeline_page(scenario_id: str, owner: str, offset: int, limit: int) -> dict[str, Any]:
    """Page the exact saved timeline artifact, never regenerate dispatch rows."""
    directory = result_directory(scenario_id)
    result = {"items": [], "total": 0, "offset": offset, "limit": limit,
              "owners": [], "source": "vehicle_timelines.json", "scope": "saved_solver_plan"}
    if directory is None:
        return result
    path = (directory / "vehicle_timelines.json").resolve()
    if not path.is_relative_to(outputs_root().resolve()):
        raise ValueError("結果の出力先が許可されたoutputフォルダー外です。")
    if not path.is_file():
        return result
    with path.open("rb") as source:
        for row in ijson.items(source, "vehicle_gantt_rows.item", use_float=True):
            vehicle = str(row.get("vehicle_id", ""))
            if vehicle not in result["owners"] and len(result["owners"]) < 250:
                result["owners"].append(vehicle)
            if owner and vehicle != owner:
                continue
            if offset <= result["total"] < offset + limit:
                result["items"].append(row)
            result["total"] += 1
    result["source"] = str(path)
    return result
