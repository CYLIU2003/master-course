from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class RuntimeScope:
    depot_ids: list[str]
    route_ids: list[str]
    service_types: list[str]


def resolve_scope(scenario_overlay: dict, routes_df: pd.DataFrame) -> RuntimeScope:
    depot_ids = list(scenario_overlay.get("depot_ids") or [])
    route_ids = list(scenario_overlay.get("route_ids") or [])
    if not route_ids and depot_ids and not routes_df.empty:
        depot_column = "depot_id" if "depot_id" in routes_df.columns else "depotId"
        route_column = "route_code" if "route_code" in routes_df.columns else "routeCode"
        filtered = routes_df[routes_df[depot_column].isin(depot_ids)]
        route_ids = [str(value) for value in filtered[route_column].tolist()]
    return RuntimeScope(
        depot_ids=depot_ids,
        route_ids=route_ids,
        service_types=["weekday", "saturday", "holiday"],
    )


def load_scoped_trips(built_dir: Path, scope: RuntimeScope) -> pd.DataFrame:
    frame = pd.read_parquet(built_dir / "trips.parquet")
    if not scope.route_ids:
        return frame.reset_index(drop=True)
    if "route_code" in frame.columns:
        mask = frame["route_code"].isin(scope.route_ids)
    elif "routeCode" in frame.columns:
        mask = frame["routeCode"].isin(scope.route_ids)
    else:
        route_series = frame["route_id"].astype(str).str.split(":").str[-1]
        mask = route_series.isin(scope.route_ids)
    return frame[mask].reset_index(drop=True)


def load_scoped_timetables(built_dir: Path, scope: RuntimeScope) -> pd.DataFrame:
    frame = pd.read_parquet(built_dir / "timetables.parquet")
    if not scope.route_ids:
        return frame.reset_index(drop=True)
    route_series = frame["route_id"].astype(str).str.split(":").str[-1]
    mask = route_series.isin(scope.route_ids)
    return frame[mask].reset_index(drop=True)
