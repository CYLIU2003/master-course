"""
src.tokyubus_gtfs.normalizers.stops — BusstopPole → CanonicalStop normalizer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..constants import TOKYO_LAT_RANGE, TOKYO_LON_RANGE
from ..models import CanonicalStop, CoordSourceType
from .helpers import data_hash, short_id

_log = logging.getLogger(__name__)


def _validate_coords(
    lat: Optional[float], lon: Optional[float]
) -> Tuple[Optional[float], Optional[float], CoordSourceType, float]:
    """Validate and classify stop coordinates."""
    if lat is None or lon is None:
        return lat, lon, CoordSourceType.unknown, 0.0

    in_range = (
        TOKYO_LAT_RANGE[0] <= lat <= TOKYO_LAT_RANGE[1]
        and TOKYO_LON_RANGE[0] <= lon <= TOKYO_LON_RANGE[1]
    )
    if in_range:
        return lat, lon, CoordSourceType.odpt_direct, 0.95
    else:
        _log.debug("Coordinates (%.4f, %.4f) outside Tokyo bounding box", lat, lon)
        return lat, lon, CoordSourceType.odpt_direct, 0.5


def normalize_busstop_poles(
    raw_data: list,
) -> Tuple[List[CanonicalStop], Dict[str, Dict[str, Any]], List[str]]:
    """
    Normalize ``odpt:BusstopPole`` records into canonical stops.

    Returns
    -------
    stops
        List of ``CanonicalStop`` models.
    stop_lookup
        Dict mapping ODPT stop ID → ``{name, lat, lon}`` for downstream use.
    warnings
        List of warning messages.
    """
    stops: List[CanonicalStop] = []
    stop_lookup: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    for item in raw_data:
        if not isinstance(item, dict):
            continue

        stop_id = str(item.get("owl:sameAs") or item.get("@id") or "")
        if not stop_id:
            continue

        # Parse coordinates
        raw_lat = item.get("geo:lat")
        raw_lon = item.get("geo:long")
        try:
            lat = float(raw_lat) if raw_lat is not None else None
        except (TypeError, ValueError):
            lat = None
        try:
            lon = float(raw_lon) if raw_lon is not None else None
        except (TypeError, ValueError):
            lon = None

        lat, lon, coord_src, coord_conf = _validate_coords(lat, lon)

        pole_number = item.get("odpt:busstopPoleNumber")
        name = str(item.get("dc:title") or short_id(stop_id, stop_id))

        stop = CanonicalStop(
            stop_id=stop_id,
            stop_code=str(pole_number or stop_id.split(":")[-1]),
            stop_name=name,
            lat=lat,
            lon=lon,
            coord_source_type=coord_src,
            coord_confidence=coord_conf,
            pole_number=str(pole_number) if pole_number is not None else None,
            odpt_id=stop_id,
            odpt_raw={
                "geo:lat": raw_lat,
                "geo:long": raw_lon,
                "odpt:busstopPoleNumber": pole_number,
                "dc:title": item.get("dc:title"),
            },
        )
        stops.append(stop)
        stop_lookup[stop_id] = {"name": name, "lat": lat, "lon": lon}

    _log.info("Normalised %d BusstopPole records", len(stops))
    return stops, stop_lookup, warnings
