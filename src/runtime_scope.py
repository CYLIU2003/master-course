from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import unicodedata

import pandas as pd

from src.tokyu_bus_data import (
    load_stop_time_rows_for_scope as load_tokyu_bus_stop_time_rows_for_scope,
    load_trip_rows_for_scope as load_tokyu_bus_trip_rows_for_scope,
    tokyu_bus_data_ready,
)
from src.tokyu_shard_loader import (
    load_stop_time_rows_for_scope,
    load_trip_rows_for_scope,
    shard_runtime_ready,
)


@dataclass
class RuntimeScope:
    depot_ids: list[str]
    route_ids: list[str]
    service_ids: list[str]
    service_date: str | None = None
    route_selectors: list[str] = field(default_factory=list)

    @property
    def service_types(self) -> list[str]:
        return list(self.service_ids)


_SERVICE_ALIASES: dict[str, tuple[str, ...]] = {
    "WEEKDAY": ("WEEKDAY", "weekday", "平日"),
    "SAT": ("SAT", "sat", "saturday", "土曜", "土曜日"),
    "SUN_HOL": (
        "SUN_HOL",
        "sun_hol",
        "sun_holiday",
        "holiday",
        "sunday",
        "日曜",
        "日曜・休日",
        "休日",
    ),
}


def _normalize_service_id(value: Any) -> str:
    raw = str(value or "").strip()
    upper = raw.upper()
    if upper in {"WEEKDAY", "WEEKDAYS"} or raw in {"weekday", "平日"}:
        return "WEEKDAY"
    if upper in {"SAT", "SATURDAY"} or raw in {"sat", "saturday", "土曜", "土曜日"}:
        return "SAT"
    if upper in {"SUN_HOL", "SUN_HOLIDAY", "HOLIDAY", "SUNDAY"} or raw in {
        "sun_hol",
        "holiday",
        "sunday",
        "日曜",
        "日曜・休日",
        "休日",
    }:
        return "SUN_HOL"
    return upper or "WEEKDAY"


def _normalize_text(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return unicodedata.normalize("NFKC", raw)


def _text_aliases(value: Any) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    tail = raw.split(":")[-1].strip()
    aliases = {
        raw,
        tail,
        _normalize_text(raw),
        _normalize_text(tail),
    }
    return {item for item in aliases if item}


def _dedupe_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        key = _normalize_text(raw)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(raw)
    return ordered


def _route_label_head(value: Any) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        return ""
    for token in ("(", "（"):
        idx = normalized.find(token)
        if idx >= 0:
            normalized = normalized[:idx]
    return normalized.strip()


def _service_aliases(values: list[str]) -> set[str]:
    aliases: set[str] = set()
    for value in values:
        normalized = _normalize_service_id(value)
        aliases.update(_SERVICE_ALIASES.get(normalized, (normalized, normalized.lower())))
    return aliases


def _overlay_like(scenario_like: dict) -> dict:
    if isinstance(scenario_like.get("scenario_overlay"), dict):
        return dict(scenario_like["scenario_overlay"])
    if isinstance(scenario_like.get("scenarioOverlay"), dict):
        return dict(scenario_like["scenarioOverlay"])
    return dict(scenario_like)


def _dispatch_scope_like(scenario_like: dict) -> dict:
    if isinstance(scenario_like.get("dispatch_scope"), dict):
        return dict(scenario_like["dispatch_scope"])
    if isinstance(scenario_like.get("dispatchScope"), dict):
        return dict(scenario_like["dispatchScope"])
    return {}


def _resolve_service_ids(scenario_like: dict) -> list[str]:
    dispatch_scope = _dispatch_scope_like(scenario_like)
    service_selection = dispatch_scope.get("serviceSelection") or {}
    selected = [
        _normalize_service_id(value)
        for value in list(service_selection.get("serviceIds") or [])
        if str(value or "").strip()
    ]
    if not selected:
        direct = dispatch_scope.get("serviceId") or scenario_like.get("service_id") or scenario_like.get("serviceId")
        if direct:
            selected = [_normalize_service_id(direct)]
    if not selected:
        simulation_config = scenario_like.get("simulation_config") or scenario_like.get("simulationConfig") or {}
        day_type = simulation_config.get("day_type") or simulation_config.get("dayType")
        if day_type:
            selected = [_normalize_service_id(day_type)]
    return selected or ["WEEKDAY"]


def _resolve_route_selectors(scenario_like: dict, route_ids: list[str]) -> list[str]:
    selectors = list(route_ids)
    if not route_ids:
        return selectors
    selected_aliases: set[str] = set()
    for route_id in route_ids:
        selected_aliases.update(_text_aliases(route_id))
    for route in list(scenario_like.get("routes") or []):
        if not isinstance(route, dict):
            continue
        route_values = [
            str(route.get(key) or "").strip()
            for key in (
                "id",
                "routeCode",
                "routeLabel",
                "name",
                "routeFamilyCode",
                "routeFamilyLabel",
            )
            if str(route.get(key) or "").strip()
        ]
        if not route_values:
            continue
        route_aliases: set[str] = set()
        for value in route_values:
            route_aliases.update(_text_aliases(value))
        if not route_aliases & selected_aliases:
            continue
        selectors.extend(route_values)
        for key in ("routeLabel", "name", "routeFamilyLabel"):
            head = _route_label_head(route.get(key))
            if head:
                selectors.append(head)
    return _dedupe_texts(selectors)


def resolve_scope(scenario_overlay: dict, routes_df: pd.DataFrame) -> RuntimeScope:
    overlay = _overlay_like(scenario_overlay)
    dispatch_scope = _dispatch_scope_like(scenario_overlay)
    depot_selection = dispatch_scope.get("depotSelection") or {}
    route_selection = dispatch_scope.get("routeSelection") or {}
    depot_ids = [
        str(value)
        for value in list(depot_selection.get("depotIds") or [])
        if str(value or "").strip()
    ]
    primary = dispatch_scope.get("depotId") or depot_selection.get("primaryDepotId")
    if primary and str(primary) not in depot_ids:
        depot_ids.insert(0, str(primary))
    if not depot_ids:
        depot_ids = list(overlay.get("depot_ids") or [])

    route_ids = [
        str(value)
        for value in list(route_selection.get("includeRouteIds") or [])
        if str(value or "").strip()
    ]
    route_ids = route_ids or [
        str(value)
        for value in list(dispatch_scope.get("effectiveRouteIds") or [])
        if str(value or "").strip()
    ]
    if not route_ids:
        route_ids = list(overlay.get("route_ids") or [])
    if not route_ids and depot_ids and not routes_df.empty:
        depot_column = "depot_id" if "depot_id" in routes_df.columns else "depotId"
        route_column = "route_code" if "route_code" in routes_df.columns else "routeCode"
        filtered = routes_df[routes_df[depot_column].isin(depot_ids)]
        route_ids = [str(value) for value in filtered[route_column].tolist()]
    return RuntimeScope(
        depot_ids=depot_ids,
        route_ids=route_ids,
        service_ids=_resolve_service_ids(scenario_overlay),
        service_date=str(
            (
                (scenario_overlay.get("simulation_config") or {}).get("service_date")
                or (scenario_overlay.get("simulationConfig") or {}).get("serviceDate")
                or ""
            )
        ).strip()
        or None,
        route_selectors=_resolve_route_selectors(scenario_overlay, route_ids),
    )


def _filter_by_service(frame: pd.DataFrame, scope: RuntimeScope) -> pd.DataFrame:
    if frame.empty or not scope.service_ids:
        return frame
    aliases = _service_aliases(scope.service_ids)
    for column in ("service_id", "serviceId", "service_type", "serviceType", "calendar"):
        if column in frame.columns:
            series = frame[column].astype(str).str.strip()
            return frame[series.isin(aliases)].reset_index(drop=True)
    return frame.reset_index(drop=True)


def _route_aliases(route_ids: list[str]) -> set[str]:
    aliases: set[str] = set()
    for value in route_ids:
        aliases.update(_text_aliases(value))
    return aliases


def _series_matches_aliases(series: pd.Series, aliases: set[str]) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()
    tail = text.where(~text.str.contains(":"), text.str.split(":").str[-1].fillna(""))
    normalized = text.map(_normalize_text)
    tail_normalized = tail.map(_normalize_text)
    return (
        text.isin(aliases)
        | tail.isin(aliases)
        | normalized.isin(aliases)
        | tail_normalized.isin(aliases)
    )


def _drop_gtfs_reconciliation_duplicates(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "trip_id" not in frame.columns:
        return frame.reset_index(drop=True)
    filtered = frame[~frame["trip_id"].astype(str).str.contains(r"__v\d+$", regex=True, na=False)]
    return filtered.reset_index(drop=True)


def _canonical_route_ids_from_lookup(
    routes_df: pd.DataFrame,
    route_selectors: list[str],
    depot_ids: list[str],
) -> set[str]:
    if routes_df.empty:
        return set()
    id_column = "id" if "id" in routes_df.columns else "route_id" if "route_id" in routes_df.columns else "routeId" if "routeId" in routes_df.columns else None
    if not id_column:
        return set()
    selector_aliases = _route_aliases(route_selectors)
    if selector_aliases:
        route_mask = pd.Series(False, index=routes_df.index)
        for column in (
            "id",
            "route_id",
            "routeId",
            "routeCode",
            "route_code",
            "routeLabel",
            "route_label",
            "name",
            "routeFamilyCode",
            "route_family_code",
            "routeFamilyLabel",
            "route_family_label",
        ):
            if column in routes_df.columns:
                route_mask = route_mask | _series_matches_aliases(routes_df[column], selector_aliases)
        if bool(route_mask.any()):
            return {
                str(value).strip()
                for value in routes_df.loc[route_mask, id_column].tolist()
                if str(value).strip()
            }
    depot_aliases = _route_aliases(depot_ids)
    if depot_aliases:
        depot_mask = pd.Series(False, index=routes_df.index)
        for column in ("depotId", "depot_id"):
            if column in routes_df.columns:
                depot_mask = depot_mask | _series_matches_aliases(routes_df[column], depot_aliases)
        if bool(depot_mask.any()):
            return {
                str(value).strip()
                for value in routes_df.loc[depot_mask, id_column].tolist()
                if str(value).strip()
            }
    return set()


def _filter_by_route(
    frame: pd.DataFrame,
    route_ids: list[str],
    *,
    route_selectors: list[str] | None = None,
    routes_df: pd.DataFrame | None = None,
    depot_ids: list[str] | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame.reset_index(drop=True)
    selectors = list(route_selectors or route_ids or [])
    depots = list(depot_ids or [])
    if not selectors and not depots:
        return frame.reset_index(drop=True)
    canonical_route_ids = _canonical_route_ids_from_lookup(
        routes_df if isinstance(routes_df, pd.DataFrame) else pd.DataFrame(),
        selectors,
        depots,
    )
    if canonical_route_ids:
        aliases = _route_aliases(list(canonical_route_ids))
        for column in ("route_id", "routeId", "id"):
            if column in frame.columns:
                return frame[_series_matches_aliases(frame[column], aliases)].reset_index(drop=True)
    aliases = _route_aliases(selectors)
    for column in ("route_code", "routeCode", "route_id", "routeId"):
        if column not in frame.columns:
            continue
        return frame[_series_matches_aliases(frame[column], aliases)].reset_index(drop=True)
    return frame.reset_index(drop=True)


def _load_routes_lookup(built_dir: Path) -> pd.DataFrame:
    routes_path = built_dir / "routes.parquet"
    if not routes_path.exists():
        return pd.DataFrame()
    return pd.read_parquet(routes_path)


def load_scoped_trips(built_dir: Path, scope: RuntimeScope) -> pd.DataFrame:
    dataset_id = built_dir.name
    if shard_runtime_ready(dataset_id):
        frame = pd.DataFrame(
            load_trip_rows_for_scope(
                dataset_id=dataset_id,
                route_ids=scope.route_ids,
                depot_ids=scope.depot_ids,
                service_ids=scope.service_ids,
            )
        )
        return frame.reset_index(drop=True)
    if tokyu_bus_data_ready(dataset_id):
        frame = pd.DataFrame(
            load_tokyu_bus_trip_rows_for_scope(
                dataset_id=dataset_id,
                route_ids=scope.route_ids,
                depot_ids=scope.depot_ids,
                service_ids=scope.service_ids,
            )
        )
        return frame.reset_index(drop=True)
    frame = _drop_gtfs_reconciliation_duplicates(pd.read_parquet(built_dir / "trips.parquet"))
    frame = _filter_by_service(frame, scope)
    return _filter_by_route(
        frame,
        scope.route_ids,
        route_selectors=scope.route_selectors,
        routes_df=_load_routes_lookup(built_dir),
        depot_ids=scope.depot_ids,
    )


def load_scoped_timetables(built_dir: Path, scope: RuntimeScope) -> pd.DataFrame:
    dataset_id = built_dir.name
    if shard_runtime_ready(dataset_id):
        frame = pd.DataFrame(
            load_stop_time_rows_for_scope(
                dataset_id=dataset_id,
                route_ids=scope.route_ids,
                depot_ids=scope.depot_ids,
                service_ids=scope.service_ids,
            )
        )
        return frame.reset_index(drop=True)
    if tokyu_bus_data_ready(dataset_id):
        frame = pd.DataFrame(
            load_tokyu_bus_stop_time_rows_for_scope(
                dataset_id=dataset_id,
                route_ids=scope.route_ids,
                depot_ids=scope.depot_ids,
                service_ids=scope.service_ids,
            )
        )
        return frame.reset_index(drop=True)
    frame = _drop_gtfs_reconciliation_duplicates(pd.read_parquet(built_dir / "timetables.parquet"))
    frame = _filter_by_service(frame, scope)
    return _filter_by_route(
        frame,
        scope.route_ids,
        route_selectors=scope.route_selectors,
        routes_df=_load_routes_lookup(built_dir),
        depot_ids=scope.depot_ids,
    )
