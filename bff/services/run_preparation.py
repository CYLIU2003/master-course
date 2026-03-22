from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from src.value_normalization import normalize_for_python


log = logging.getLogger("run_prep")


def _normalize_solver_mode(mode: Any) -> str:
    normalized = str(mode or "").strip().lower()
    alias_map = {
        "milp": "mode_milp_only",
        "exact": "mode_milp_only",
        "alns": "mode_alns_only",
        "heuristic": "mode_alns_only",
        "hybrid": "mode_alns_milp",
        "ga": "mode_ga_only",
        "abc": "mode_abc_only",
    }
    return alias_map.get(normalized, str(mode or "").strip() or "mode_milp_only")


def solver_prepare_profile(mode: Any) -> dict[str, Any]:
    solver_mode_effective = _normalize_solver_mode(mode)
    if solver_mode_effective == "mode_milp_only":
        return {
            "solver_mode_effective": solver_mode_effective,
            "profile": "milp_exact",
            "dispatch_rebuild_required": False,
            "preferred_execution": "optimization",
            "notes": [
                "prepared scope is used directly",
                "MILP exact solve consumes canonical ProblemData",
            ],
        }
    if solver_mode_effective == "mode_alns_only":
        return {
            "solver_mode_effective": solver_mode_effective,
            "profile": "metaheuristic_alns",
            "dispatch_rebuild_required": False,
            "preferred_execution": "optimization",
            "notes": [
                "prepared scope is used directly",
                "ALNS consumes canonical ProblemData without dispatch rebuild",
            ],
        }
    if solver_mode_effective == "mode_ga_only":
        return {
            "solver_mode_effective": solver_mode_effective,
            "profile": "metaheuristic_ga",
            "dispatch_rebuild_required": False,
            "preferred_execution": "optimization",
            "notes": [
                "prepared scope is used directly",
                "GA mode reuses canonical ProblemData preparation",
            ],
        }
    if solver_mode_effective == "mode_abc_only":
        return {
            "solver_mode_effective": solver_mode_effective,
            "profile": "metaheuristic_abc",
            "dispatch_rebuild_required": False,
            "preferred_execution": "optimization",
            "notes": [
                "prepared scope is used directly",
                "ABC mode reuses canonical ProblemData preparation",
            ],
        }
    return {
        "solver_mode_effective": solver_mode_effective,
        "profile": "hybrid_seeded",
        "dispatch_rebuild_required": False,
        "preferred_execution": "optimization",
        "notes": [
            "prepared scope is used directly",
            "hybrid mode consumes canonical ProblemData with ALNS+MILP pipeline",
        ],
    }


@dataclass
class RunPreparation:
    scenario_id: str
    dataset_version: str
    scenario_hash: str
    solver_input_path: Optional[Path]
    scope_summary: dict
    prepared_input_id: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    prepared_at: float = field(default_factory=time.time)
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None and self.solver_input_path is not None


_prep_cache: dict[tuple[str, str, str], RunPreparation] = {}
_VOLATILE_HASH_KEYS = {
    "updatedAt",
    "createdAt",
    "status",
    "meta",
    "stats",
    "refs",
    "timetable_rows",
    "stop_timetables",
    "trips",
    "graph",
    "blocks",
    "duties",
    "dispatch_plan",
    "simulation_result",
    "optimization_result",
    "datasetStatus",
    "dataset_status",
    "prepared_input_id",
    "preparedInputId",
    "prepared_at",
    "selectedDepotIds",
    "selectedRouteIds",
    "serviceIds",
}


def _canonicalize_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonicalize_for_hash(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_HASH_KEYS
        }
    if isinstance(value, list):
        return [_canonicalize_for_hash(item) for item in value]
    return value


def _scenario_hash(scenario_dict: dict) -> str:
    canonical = json.dumps(
        _canonicalize_for_hash(scenario_dict),
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _prepared_input_id(scenario_hash: str) -> str:
    return f"prepared-{scenario_hash}"


def _as_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [
        {str(key): normalize_for_python(value) for key, value in record.items()}
        for record in frame.to_dict(orient="records")
    ]


def _rows_to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _scenario_value(scenario: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in scenario and scenario[key] is not None:
            return scenario[key]
    return default


def _scenario_id(scenario: dict) -> str:
    meta = scenario.get("meta") or {}
    return str(
        scenario.get("id")
        or scenario.get("scenario_id")
        or meta.get("id")
        or "unknown"
    )


def _dataset_version(scenario: dict) -> str:
    meta = scenario.get("meta") or {}
    overlay = _scenario_value(scenario, "scenario_overlay", "scenarioOverlay", default={}) or {}
    feed_context = _scenario_value(scenario, "feed_context", "feedContext", default={}) or {}
    return str(
        scenario.get("datasetVersion")
        or scenario.get("dataset_version")
        or meta.get("datasetVersion")
        or overlay.get("dataset_version")
        or overlay.get("datasetVersion")
        or feed_context.get("snapshotId")
        or "unknown"
    )


def _dataset_id(scenario: dict) -> str:
    meta = scenario.get("meta") or {}
    overlay = _scenario_value(scenario, "scenario_overlay", "scenarioOverlay", default={}) or {}
    feed_context = _scenario_value(scenario, "feed_context", "feedContext", default={}) or {}
    return str(
        scenario.get("datasetId")
        or scenario.get("dataset_id")
        or meta.get("datasetId")
        or overlay.get("dataset_id")
        or overlay.get("datasetId")
        or feed_context.get("datasetId")
        or "tokyu_core"
    )


def _random_seed(scenario: dict) -> int:
    meta = scenario.get("meta") or {}
    overlay = _scenario_value(scenario, "scenario_overlay", "scenarioOverlay", default={}) or {}
    simulation_config = _scenario_value(
        scenario,
        "simulation_config",
        "simulationConfig",
        default={},
    ) or {}
    raw = (
        scenario.get("randomSeed")
        or scenario.get("random_seed")
        or meta.get("randomSeed")
        or overlay.get("random_seed")
        or overlay.get("randomSeed")
        or simulation_config.get("random_seed")
        or simulation_config.get("randomSeed")
        or 42
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 42


def _id_aliases(value: Any) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    return {raw, raw.split(":")[-1]}


def _select_items_by_ids(items: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    if not items:
        return []
    if not ids:
        return [dict(item) for item in items]
    selected_ids: set[str] = set()
    for item in ids:
        selected_ids.update(_id_aliases(item))
    return [
        dict(item)
        for item in items
        if _id_aliases(item.get("id") or item.get("routeId") or item.get("depotId") or "") & selected_ids
    ]


def _load_optional_stops(built_dir: Path, timetables_df: pd.DataFrame) -> list[dict[str, Any]]:
    stops_path = built_dir / "stops.parquet"
    if not stops_path.exists():
        return _derived_stops_from_timetables(timetables_df)
    frame = pd.read_parquet(stops_path)
    if frame.empty:
        return _derived_stops_from_timetables(timetables_df)
    if timetables_df.empty:
        return _as_records(frame)
    referenced_stop_ids: set[str] = set()
    for column in ("stop_id", "stopId", "origin", "destination"):
        if column in timetables_df.columns:
            referenced_stop_ids.update(
                str(value)
                for value in timetables_df[column].dropna().astype(str).tolist()
                if str(value).strip()
            )
    if not referenced_stop_ids:
        return _as_records(frame)
    for column in ("id", "stop_id", "stopId"):
        if column in frame.columns:
            filtered = frame[frame[column].astype(str).isin(referenced_stop_ids)].reset_index(drop=True)
            if not filtered.empty:
                return _as_records(filtered)
    return _derived_stops_from_timetables(timetables_df) or _as_records(frame)


def _derived_stops_from_timetables(timetables_df: pd.DataFrame) -> list[dict[str, Any]]:
    if timetables_df.empty:
        return []
    rows = timetables_df.to_dict(orient="records")
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    stop_id_column = "stop_id" if "stop_id" in timetables_df.columns else "stopId" if "stopId" in timetables_df.columns else None
    stop_name_column = "stop_name" if "stop_name" in timetables_df.columns else "stopName" if "stopName" in timetables_df.columns else None
    if stop_id_column:
        for row in rows:
            stop_id = str(row.get(stop_id_column) or "").strip()
            if not stop_id or stop_id in seen_ids:
                continue
            seen_ids.add(stop_id)
            items.append(
                {
                    "id": stop_id,
                    "name": str(row.get(stop_name_column) or stop_id) if stop_name_column else stop_id,
                    "source": "prepared_input_inferred",
                }
            )
        if items:
            return items
    for column, name_column in (("origin_stop_id", "origin"), ("destination_stop_id", "destination")):
        if column not in timetables_df.columns:
            continue
        for row in rows:
            stop_id = str(row.get(column) or "").strip()
            if not stop_id or stop_id in seen_ids:
                continue
            seen_ids.add(stop_id)
            items.append(
                {
                    "id": stop_id,
                    "name": str(row.get(name_column) or stop_id),
                    "source": "prepared_input_inferred",
                }
            )
    return items


def _load_scope_frames(
    scenario: dict,
    *,
    built_dir: Path,
    scope,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    try:
        from src import tokyu_shard_loader

        dataset_id = _dataset_id(scenario)
        if tokyu_shard_loader.shard_runtime_ready(dataset_id):
            trip_rows = tokyu_shard_loader.load_trip_rows_for_scope(
                dataset_id=dataset_id,
                route_ids=scope.route_ids,
                depot_ids=scope.depot_ids,
                service_ids=scope.service_ids,
            )
            stop_time_rows = tokyu_shard_loader.load_stop_time_rows_for_scope(
                dataset_id=dataset_id,
                route_ids=scope.route_ids,
                depot_ids=scope.depot_ids,
                service_ids=scope.service_ids,
            )
            return (
                _rows_to_frame(trip_rows),
                _rows_to_frame(stop_time_rows),
                "tokyu_shard",
            )
    except Exception as exc:
        log.warning("Shard runtime load failed; falling back to built parquet: %s", exc)

    from src.runtime_scope import load_scoped_timetables, load_scoped_trips

    try:
        trips_df = load_scoped_trips(built_dir, scope)
        timetables_df = load_scoped_timetables(built_dir, scope)
        if not trips_df.empty:
            return (trips_df, timetables_df, "built_parquet")
    except Exception as exc:
        log.warning("Built parquet load failed; falling back to timetable_rows: %s", exc)

    timetable_rows = list(scenario.get("timetable_rows") or [])
    if timetable_rows:
        route_id_set = set(scope.route_ids) if scope.route_ids else None
        service_id_set = set(scope.service_ids) if scope.service_ids else None
        _vn_pattern = re.compile(r"__v\d+$")
        scoped_rows = [
            row for row in timetable_rows
            if (route_id_set is None or str(row.get("route_id") or "").strip() in route_id_set)
            and (service_id_set is None or str(row.get("service_id") or "").strip() in service_id_set)
            and not _vn_pattern.search(str(row.get("trip_id") or ""))
        ]
        return (
            _rows_to_frame(scoped_rows),
            _rows_to_frame([]),
            "timetable_rows_fallback",
        )

    return (_rows_to_frame([]), _rows_to_frame([]), "built_parquet")


def _prepared_input_dir(scenarios_dir: Path, scenario_id: str) -> Path:
    if scenarios_dir.name == "prepared_inputs":
        return scenarios_dir / scenario_id
    return scenarios_dir / scenario_id / "prepared_inputs"


def _build_canonical_input(
    *,
    scenario: dict,
    prepared_input_id: str,
    scenario_id: str,
    dataset_version: str,
    scenario_hash: str,
    scope,
    trips_df: pd.DataFrame,
    timetables_df: pd.DataFrame,
    stops: list[dict[str, Any]],
) -> dict[str, Any]:
    scenario_overlay = dict(
        _scenario_value(scenario, "scenario_overlay", "scenarioOverlay", default={}) or {}
    )
    dispatch_scope = dict(
        _scenario_value(scenario, "dispatch_scope", "dispatchScope", default={}) or {}
    )
    simulation_config = dict(_scenario_value(scenario, "simulation_config", "simulationConfig", default={}) or {})
    dataset_id = _dataset_id(scenario)
    random_seed = _random_seed(scenario)
    vehicles = [dict(item) for item in list(scenario.get("vehicles") or [])]
    chargers = [dict(item) for item in list(scenario.get("chargers") or [])]
    solver_mode_requested = str(
        simulation_config.get("solver_mode")
        or (scenario_overlay.get("solver_config") or {}).get("mode")
        or "mode_milp_only"
    ).strip() or "mode_milp_only"
    solver_mode_effective = _normalize_solver_mode(solver_mode_requested)
    prepare_profile = solver_prepare_profile(solver_mode_effective)
    depots = _select_items_by_ids(
        [dict(item) for item in list(scenario.get("depots") or [])],
        list(scope.depot_ids),
    )
    routes = _select_items_by_ids(
        [dict(item) for item in list(scenario.get("routes") or [])],
        list(scope.route_ids),
    )
    trip_records = _as_records(trips_df)
    stop_time_records = _as_records(timetables_df)
    route_index = {
        str(route.get("id") or ""): idx
        for idx, route in enumerate(routes)
        if route.get("id") is not None
    }
    trip_index = {
        str(item.get("trip_id") or ""): idx
        for idx, item in enumerate(trip_records)
        if item.get("trip_id") is not None
    }
    depot_index = {
        str(depot.get("id") or depot.get("depotId") or ""): idx
        for idx, depot in enumerate(depots)
        if depot.get("id") is not None or depot.get("depotId") is not None
    }
    vehicle_index = {
        str(vehicle.get("id") or ""): idx
        for idx, vehicle in enumerate(vehicles)
        if vehicle.get("id") is not None
    }
    charger_index = {
        str(charger.get("id") or charger.get("charger_id") or ""): idx
        for idx, charger in enumerate(chargers)
        if charger.get("id") is not None or charger.get("charger_id") is not None
    }

    return {
        "prepared_input_id": prepared_input_id,
        "scenario_id": scenario_id,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "random_seed": random_seed,
        "scenario_hash": scenario_hash,
        "prepared_at": time.time(),
        "solver_mode_requested": solver_mode_requested,
        "solver_mode_effective": solver_mode_effective,
        "prepare_profile": prepare_profile,
        "depot_ids": list(scope.depot_ids),
        "route_ids": list(scope.route_ids),
        "service_ids": list(scope.service_ids),
        "service_date": scope.service_date,
        "primary_depot_id": scope.depot_ids[0] if scope.depot_ids else None,
        "trip_count": len(trip_records),
        "timetable_row_count": len(stop_time_records),
        "scope": {
            "depot_ids": list(scope.depot_ids),
            "route_ids": list(scope.route_ids),
            "service_ids": list(scope.service_ids),
            "service_date": scope.service_date,
            "primary_depot_id": scope.depot_ids[0] if scope.depot_ids else None,
        },
        "counts": {
            "depot_count": len(scope.depot_ids),
            "route_count": len(scope.route_ids),
            "trip_count": len(trips_df),
            "timetable_row_count": len(timetables_df),
            "stop_count": len(stops),
            "vehicle_count": len(vehicles),
            "charger_count": len(chargers),
        },
        "dispatch_scope": dispatch_scope,
        "scenario_overlay": scenario_overlay,
        "simulation_config": simulation_config,
        "depots": depots,
        "routes": routes,
        "vehicles": vehicles,
        "chargers": chargers,
        "trips": trip_records,
        "stop_time_sequences": stop_time_records,
        "stops": stops,
        "solver_ready_ids": {
            "depot_index": depot_index,
            "route_index": route_index,
            "trip_index": trip_index,
            "vehicle_index": vehicle_index,
            "charger_index": charger_index,
        },
    }


def materialize_scenario_from_prepared_input(
    scenario: dict[str, Any],
    prepared_input: dict[str, Any],
) -> dict[str, Any]:
    hydrated = dict(scenario)
    meta = dict(hydrated.get("meta") or {})
    meta["selectedDepotIds"] = list(prepared_input.get("depot_ids") or [])
    meta["selectedRouteIds"] = list(prepared_input.get("route_ids") or [])
    meta["serviceIds"] = list(prepared_input.get("service_ids") or [])
    hydrated["meta"] = meta

    for key in ("scenario_overlay", "dispatch_scope", "simulation_config"):
        value = prepared_input.get(key)
        if isinstance(value, dict):
            hydrated[key] = dict(value)

    for key in ("depots", "routes", "vehicles", "chargers", "stops", "trips"):
        value = prepared_input.get(key)
        if isinstance(value, list):
            hydrated[key] = [
                dict(item)
                for item in value
                if isinstance(item, dict)
            ]

    stop_time_sequences = prepared_input.get("stop_time_sequences")
    if isinstance(stop_time_sequences, list):
        hydrated["stop_timetables"] = [
            dict(item)
            for item in stop_time_sequences
            if isinstance(item, dict)
        ]

    if isinstance(prepared_input.get("trips"), list):
        # Treat the prepared scoped trips as the canonical timetable rows for
        # optimization/simulation paths that previously depended on persisted
        # dispatch artifacts.
        hydrated["timetable_rows"] = [
            dict(item)
            for item in prepared_input.get("trips") or []
            if isinstance(item, dict)
        ]

    hydrated["prepared_input_id"] = str(prepared_input.get("prepared_input_id") or "")
    hydrated["prepared_scope_summary"] = dict(prepared_input.get("scope") or {})
    hydrated["prepare_profile"] = dict(prepared_input.get("prepare_profile") or {})
    return hydrated


def get_or_build_run_preparation(
    scenario: dict,
    built_dir: Path,
    scenarios_dir: Path,
    routes_df,
) -> RunPreparation:
    scenario_id = _scenario_id(scenario)
    dataset_version = _dataset_version(scenario)
    scenario_hash = _scenario_hash(scenario)
    cache_key = (scenario_id, dataset_version, scenario_hash)

    if cache_key in _prep_cache:
        cached = _prep_cache[cache_key]
        if cached.is_valid:
            log.debug("run_prep cache HIT: %s %s", scenario_id, scenario_hash)
            return cached
        log.debug("run_prep cache INVALID: %s", scenario_id)

    log.info("Building run preparation for scenario %s (hash=%s)", scenario_id, scenario_hash)
    prep = _build_run_preparation(scenario, built_dir, scenarios_dir, routes_df, scenario_hash)
    _prep_cache[cache_key] = prep
    return prep


def _build_run_preparation(
    scenario: dict,
    built_dir: Path,
    scenarios_dir: Path,
    routes_df,
    scenario_hash: str,
) -> RunPreparation:
    scenario_id = _scenario_id(scenario)
    dataset_version = _dataset_version(scenario)
    try:
        from src.runtime_scope import resolve_scope

        scope = resolve_scope(scenario, routes_df if routes_df is not None else pd.DataFrame())
        trips_df, timetables_df, load_source = _load_scope_frames(
            scenario,
            built_dir=built_dir,
            scope=scope,
        )
        stops = _load_optional_stops(built_dir, timetables_df)
        warnings: list[str] = []
        if not scope.depot_ids:
            warnings.append("No depot is selected in the current builder scope.")
        if not scope.route_ids:
            warnings.append("No routes are selected in the current builder scope.")
        if trips_df.empty:
            warnings.append("Scoped built dataset returned zero trips for the current selection.")
        if load_source == "tokyu_shard":
            warnings.append("Prepared input was assembled from Tokyu shard runtime artifacts.")

        prepared_input_id = _prepared_input_id(scenario_hash)
        solver_input = normalize_for_python(_build_canonical_input(
            scenario=scenario,
            prepared_input_id=prepared_input_id,
            scenario_id=scenario_id,
            dataset_version=dataset_version,
            scenario_hash=scenario_hash,
            scope=scope,
            trips_df=trips_df,
            timetables_df=timetables_df,
            stops=stops,
        ))
        scenario_dir = _prepared_input_dir(scenarios_dir, scenario_id)
        scenario_dir.mkdir(parents=True, exist_ok=True)
        solver_input_path = scenario_dir / f"{prepared_input_id}.json"
        solver_input_path.write_text(
            json.dumps(solver_input, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return RunPreparation(
            scenario_id=scenario_id,
            dataset_version=dataset_version,
            scenario_hash=scenario_hash,
            solver_input_path=solver_input_path,
            prepared_input_id=prepared_input_id,
            warnings=warnings,
            scope_summary={
                "depot_ids": scope.depot_ids,
                "route_ids": scope.route_ids,
                "service_ids": scope.service_ids,
                "service_date": scope.service_date,
                "prepared_input_id": prepared_input_id,
                "primary_depot_id": scope.depot_ids[0] if scope.depot_ids else None,
                "trip_count": len(trips_df),
                "timetable_row_count": len(timetables_df),
                "load_source": load_source,
            },
        )
    except Exception as exc:
        log.error("run_preparation failed for %s: %s", scenario_id, exc)
        return RunPreparation(
            scenario_id=scenario_id,
            dataset_version=dataset_version,
            scenario_hash=scenario_hash,
            solver_input_path=None,
            scope_summary={},
            error=str(exc),
        )


def load_prepared_input(
    *,
    scenario_id: str,
    prepared_input_id: str,
    scenarios_dir: Path,
) -> dict[str, Any]:
    path = _prepared_input_dir(scenarios_dir, scenario_id) / f"{prepared_input_id}.json"
    if not path.exists():
        raise FileNotFoundError(str(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def invalidate_scenario(scenario_id: str) -> None:
    keys = [key for key in _prep_cache if key[0] == scenario_id]
    for key in keys:
        del _prep_cache[key]
    if keys:
        log.info("Invalidated %s run_prep cache entries for %s", len(keys), scenario_id)
