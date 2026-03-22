from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

from bff.services.service_ids import canonical_service_id
from src.research_dataset_loader import get_dataset_status


def _trip_artifact_path(dataset_id: str) -> Path | None:
    status = get_dataset_status(dataset_id)
    path = Path(str((status.get("paths") or {}).get("trips") or "").strip())
    if not path.exists():
        return None
    return path


@lru_cache(maxsize=32)
def route_trip_counts_for_dataset(
    dataset_id: str,
    service_id: str | None = None,
) -> Dict[str, int]:
    trip_path = _trip_artifact_path(str(dataset_id or "").strip())
    if trip_path is None:
        return {}

    frame = pd.read_parquet(trip_path, columns=["route_id", "service_id"])
    if frame.empty or "route_id" not in frame.columns:
        return {}

    if service_id and "service_id" in frame.columns:
        selected_service_id = canonical_service_id(service_id)
        frame = frame[
            frame["service_id"].map(canonical_service_id) == selected_service_id
        ]
    if frame.empty:
        return {}

    counts = frame["route_id"].astype(str).value_counts().to_dict()
    return {
        route_id: int(count)
        for route_id, count in counts.items()
        if str(route_id).strip()
    }


def filter_linked_route_ids(
    route_ids: Iterable[str],
    route_trip_counts: Dict[str, int],
) -> List[str]:
    normalized = [
        str(route_id).strip()
        for route_id in route_ids
        if str(route_id).strip()
    ]
    if not route_trip_counts:
        return normalized
    return [
        route_id
        for route_id in normalized
        if int(route_trip_counts.get(route_id) or 0) > 0
    ]
