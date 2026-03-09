"""
src.tokyubus_gtfs.models — Pydantic models for the canonical transit layer.

These models define the internal representation (Layer B).
They are separate from ``src.schemas.*`` (dispatch domain) and from raw
ODPT JSON structures, providing a stable intermediate form that can be:
  - serialised to JSONL / Parquet for canonical storage
  - exported to GTFS
  - fed to research feature builders

Design rules:
  - Preserve both original ODPT strings AND normalised values.
  - Never discard raw identifiers.
  - Coordinates carry ``coord_source_type`` metadata.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CoordSourceType(str, Enum):
    """How a coordinate was obtained."""

    odpt_direct = "odpt_direct"  # from ODPT geo:lat / geo:long
    gtfs_import = "gtfs_import"  # from GTFS stops.txt
    geocoded = "geocoded"  # reverse-geocoded from address
    imputed_mean = "imputed_mean"  # mean of adjacent stops
    imputed_snap = "imputed_snap"  # snapped to nearest road
    unknown = "unknown"


class RouteVariantType(str, Enum):
    main = "main"
    main_outbound = "main_outbound"
    main_inbound = "main_inbound"
    short_turn = "short_turn"
    branch = "branch"
    depot_out = "depot_out"
    depot_in = "depot_in"
    unknown = "unknown"


class CanonicalDirection(str, Enum):
    outbound = "outbound"
    inbound = "inbound"
    circular = "circular"
    unknown = "unknown"


class ServiceDayType(str, Enum):
    weekday = "WEEKDAY"
    saturday = "SAT"
    sunday_holiday = "SUN_HOL"


# ---------------------------------------------------------------------------
# Layer B: Canonical entities
# ---------------------------------------------------------------------------


class Operator(BaseModel):
    """Transit operator."""

    operator_id: str
    name: str
    name_en: str = ""
    url: str = ""
    phone: str = ""
    timezone: str = "Asia/Tokyo"
    lang: str = "ja"


class CanonicalStop(BaseModel):
    """Normalised bus stop / pole."""

    stop_id: str
    stop_code: str = ""
    stop_name: str
    stop_name_en: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    coord_source_type: CoordSourceType = CoordSourceType.unknown
    coord_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    pole_number: Optional[str] = None
    parent_station_id: Optional[str] = None
    zone_id: Optional[str] = None
    # raw provenance
    odpt_id: str = ""
    odpt_raw: Dict[str, Any] = Field(default_factory=dict)


class CanonicalRoute(BaseModel):
    """Passenger-facing public route family."""

    route_id: str
    route_code: str = ""
    route_name: str
    route_name_en: str = ""
    operator_id: str = ""
    route_color: str = ""
    route_type: int = 3  # GTFS: 3 = bus
    # terminal info
    origin_stop_id: str = ""
    destination_stop_id: str = ""
    origin_name: str = ""
    destination_name: str = ""
    # metrics
    distance_km: float = 0.0
    trip_count: int = 0
    stop_count: int = 0
    route_family_code: Optional[str] = None
    route_family_label: Optional[str] = None
    primary_pattern_id: Optional[str] = None
    family_sort_order: int = 0
    classification_confidence: float = 0.0
    classification_reasons: List[str] = Field(default_factory=list)


class CanonicalRoutePattern(BaseModel):
    """Fine-grained ODPT pattern mapped into a public route family."""

    pattern_id: str
    route_id: str
    pattern_code: Optional[str] = None
    pattern_role: RouteVariantType = RouteVariantType.unknown
    direction_bucket: Optional[int] = Field(default=None, ge=0, le=1)
    shape_id: Optional[str] = None
    first_stop_id: str = ""
    last_stop_id: str = ""
    first_stop_name: str = ""
    last_stop_name: str = ""
    stop_count: int = 0
    distance_km: float = 0.0
    is_passenger_service: bool = True
    include_in_public_gtfs: bool = True
    route_short_name_hint: str = ""
    route_long_name_hint: str = ""
    odpt_pattern_id: str = ""
    odpt_busroute_id: str = ""
    odpt_raw_title: str = ""
    classification_confidence: float = 0.0
    classification_reasons: List[str] = Field(default_factory=list)


class CanonicalRouteStop(BaseModel):
    """A stop within a route's ordered sequence."""

    pattern_id: str
    route_id: str
    stop_id: str
    stop_sequence: int
    stop_name: str = ""
    # ODPT provenance
    odpt_pattern_id: str = ""
    distance_from_start_m: Optional[float] = None


class CanonicalService(BaseModel):
    """Service calendar entry."""

    service_id: str
    service_name: str = ""
    monday: bool = False
    tuesday: bool = False
    wednesday: bool = False
    thursday: bool = False
    friday: bool = False
    saturday: bool = False
    sunday: bool = False
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # ODPT provenance
    odpt_calendar_raw: str = ""


class CanonicalTrip(BaseModel):
    """A single bus trip (one run of one route)."""

    trip_id: str
    route_id: str
    pattern_id: str = ""
    service_id: str
    direction: CanonicalDirection = CanonicalDirection.unknown
    direction_id: Optional[int] = Field(default=None, ge=0, le=1)
    trip_index: int = 0
    # terminal info
    origin_stop_id: str = ""
    destination_stop_id: str = ""
    origin_name: str = ""
    destination_name: str = ""
    # time
    departure_time: str = ""  # "HH:MM:SS" — may exceed 24h for overnight
    arrival_time: str = ""
    departure_seconds: Optional[int] = None  # seconds from midnight
    arrival_seconds: Optional[int] = None
    shape_id: str = ""
    office_id: Optional[str] = None
    # metrics
    distance_km: float = 0.0
    runtime_min: float = 0.0
    # vehicle
    allowed_vehicle_types: List[str] = Field(default_factory=lambda: ["BEV", "ICE"])
    trip_category: str = "revenue"
    trip_role: str = "service"
    is_public_trip: bool = True
    # ODPT provenance
    odpt_timetable_id: str = ""
    odpt_pattern_id: str = ""
    odpt_calendar_raw: str = ""


class CanonicalTripStopTime(BaseModel):
    """Arrival/departure at each stop within a trip."""

    trip_id: str
    stop_id: str
    stop_sequence: int
    arrival_time: Optional[str] = None  # "HH:MM:SS"
    departure_time: Optional[str] = None
    arrival_seconds: Optional[int] = None
    departure_seconds: Optional[int] = None
    stop_name: str = ""
    # ODPT provenance
    odpt_raw_arrival: Optional[str] = None
    odpt_raw_departure: Optional[str] = None


class CanonicalStopTimetable(BaseModel):
    """
    Per-stop timetable (from BusstopPoleTimetable).
    Used for reconciliation, not direct GTFS export.
    """

    timetable_id: str
    stop_id: str
    stop_name: str = ""
    service_id: str = ""
    odpt_calendar_raw: str = ""
    items: List[Dict[str, Any]] = Field(default_factory=list)


class CanonicalStopPole(BaseModel):
    """Stop pole metadata kept separate from aggregated stop facts."""

    stop_pole_id: str
    stop_id: str
    stop_name: str = ""
    pole_number: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    odpt_id: str = ""


class CanonicalShapePoint(BaseModel):
    """Polyline point approximating a route shape from stop order."""

    shape_id: str
    shape_pt_sequence: int
    shape_pt_lat: float
    shape_pt_lon: float
    shape_dist_traveled_km: float = 0.0
    route_id: str = ""
    stop_id: str = ""


class SourceLineage(BaseModel):
    """Provenance mapping from canonical table to raw source resource."""

    table_name: str
    source_type: str
    source_path: str = ""
    resource_type: str = ""
    snapshot_id: str = ""
    record_count: int = 0
    sha256: str = ""
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Pipeline result container
# ---------------------------------------------------------------------------


class NormalizationSummary(BaseModel):
    """Summary of a full normalisation run."""

    feed_id: str = ""
    snapshot_id: str = ""
    dataset_id: str = ""
    raw_archive_path: str = ""
    canonical_dir: str = ""
    normalised_at: str = ""
    entity_counts: Dict[str, int] = Field(default_factory=dict)
    reconciliation: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    rebuilt_tables: List[str] = Field(default_factory=list)
    reused_tables: List[str] = Field(default_factory=list)
