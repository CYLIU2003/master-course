"""
src/dispatch/models.py

Core frozen dataclasses for the timetable-driven dispatch planning system.
These are dispatch-layer models, intentionally separate from src/schemas/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import unicodedata


def hhmm_to_min(hhmm: str) -> int:
    """Convert 'HH:MM' string to integer minutes from midnight."""
    text = str(hhmm or "00:00").strip()
    parts = text.split(":", 1)
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return 0
    return max(h, 0) * 60 + max(m, 0)


# ---------------------------------------------------------------------------
# Input / rule models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Trip:
    """A single revenue trip from the timetable."""

    trip_id: str
    route_id: str
    origin: str
    destination: str
    departure_time: str  # "HH:MM"
    arrival_time: str  # "HH:MM"
    distance_km: float
    allowed_vehicle_types: Tuple[str, ...]  # e.g. ("BEV", "ICE")
    origin_stop_id: str = ""
    destination_stop_id: str = ""
    route_family_code: str = ""
    # Optional metadata preserved from timetable_rows for smarter dispatching.
    # direction helps greedy dispatcher prefer the return leg on the same route;
    # route_variant_type lets the dispatcher treat depot-moves differently.
    direction: str = "unknown"            # "outbound" | "inbound" | "unknown"
    route_variant_type: str = "unknown"   # "main_outbound" | "main_inbound"
                                          # | "short_turn" | "branch"
                                          # | "depot_in" | "depot_out" | "unknown"

    @property
    def departure_min(self) -> int:
        return hhmm_to_min(self.departure_time)

    @property
    def arrival_min(self) -> int:
        return hhmm_to_min(self.arrival_time)


@dataclass(frozen=True)
class TurnaroundRule:
    """Minimum layover (minutes) required at a given stop."""

    stop_id: str
    min_turnaround_min: int


@dataclass(frozen=True)
class DeadheadRule:
    """Deadhead travel time (minutes) between two stops."""

    from_stop: str
    to_stop: str
    travel_time_min: int


@dataclass(frozen=True)
class VehicleProfile:
    """Capability descriptor for a vehicle type."""

    vehicle_type: str  # e.g. "BEV", "ICE"
    # EV fields (optional)
    battery_capacity_kwh: Optional[float] = None
    energy_consumption_kwh_per_km: Optional[float] = None
    # Engine fields (optional)
    fuel_tank_capacity_l: Optional[float] = None
    fuel_consumption_l_per_km: Optional[float] = None
    
    fixed_use_cost_jpy: float = 0.0


# ---------------------------------------------------------------------------
# Result / output models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConnectionResult:
    """Result of a feasibility check between two trips."""

    feasible: bool
    reason_code: str
    reason: str  # human-readable explanation
    deadhead_time_min: int = 0  # 0 when origin == destination
    turnaround_time_min: int = 0
    slack_min: int = 0  # how many spare minutes remain


@dataclass(frozen=True)
class ConnectionArc:
    """One analyzed candidate edge between two trips for a vehicle type."""

    from_trip_id: str
    to_trip_id: str
    vehicle_type: str
    deadhead_time_min: int
    turnaround_time_min: int
    slack_min: int
    feasible: bool
    reason_code: str
    reason: str


@dataclass(frozen=True)
class DutyLeg:
    """One revenue trip inside a VehicleDuty."""

    trip: Trip
    deadhead_from_prev_min: int = 0  # deadhead before this trip


@dataclass(frozen=True)
class VehicleDuty:
    """An ordered sequence of trips assigned to one vehicle."""

    duty_id: str
    vehicle_type: str
    legs: Tuple[DutyLeg, ...]

    @property
    def trips(self) -> List[Trip]:
        return [leg.trip for leg in self.legs]

    @property
    def trip_ids(self) -> List[str]:
        return [leg.trip.trip_id for leg in self.legs]


@dataclass(frozen=True)
class VehicleBlock:
    """
    One vehicle-continuous chain of trips.

    This sits between trip-level feasibility and final dispatch planning:
      Trip -> ConnectionArc -> VehicleBlock -> DispatchPlan
    """

    block_id: str
    vehicle_type: str
    trip_ids: Tuple[str, ...]


@dataclass(frozen=True)
class DispatchPlan:
    """
    Final dispatch-facing output container.

    Duties remain the validated execution unit. Blocks provide a lighter-weight
    chain abstraction that heuristic / optimization layers can build first.
    """

    plan_id: str
    vehicle_blocks: Tuple[VehicleBlock, ...] = ()
    duties: Tuple[VehicleDuty, ...] = ()
    charging_plan: Tuple[dict, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a VehicleDuty."""

    valid: bool
    errors: Tuple[str, ...]  # empty tuple when valid

    @classmethod
    def ok(cls) -> "ValidationResult":
        return cls(valid=True, errors=())

    @classmethod
    def fail(cls, *messages: str) -> "ValidationResult":
        return cls(valid=False, errors=tuple(messages))


# ---------------------------------------------------------------------------
# Orchestration context
# ---------------------------------------------------------------------------


@dataclass
class DispatchContext:
    """
    All inputs required to run the dispatch pipeline for one service day.
    Passed by reference through all pipeline stages.
    """

    service_date: str  # "YYYY-MM-DD"
    trips: List[Trip]
    turnaround_rules: Dict[str, TurnaroundRule]  # keyed by stop_id
    deadhead_rules: Dict[Tuple[str, str], DeadheadRule]  # keyed by (from, to)
    vehicle_profiles: Dict[str, VehicleProfile]  # keyed by vehicle_type
    default_turnaround_min: int = 10  # fallback when no rule
    # Swap permissions: whether vehicles may serve trips from other routes/depots
    allow_intra_depot_swap: bool = False   # permit vehicle swap across routes in same depot
    allow_inter_depot_swap: bool = False   # permit vehicle swap across different depots
    location_aliases: Dict[str, Tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        alias_sets: Dict[str, set[str]] = {}

        def _register(alias: str, canonical: str) -> None:
            alias_norm = _normalize_location_key(alias)
            canonical_text = str(canonical or "").strip()
            if not alias_norm or not canonical_text:
                return
            alias_sets.setdefault(alias_norm, set()).add(canonical_text)

        for trip in self.trips:
            _register(trip.origin, trip.origin)
            _register(trip.origin, trip.origin_stop_id or trip.origin)
            _register(trip.origin_stop_id, trip.origin_stop_id)
            _register(trip.destination, trip.destination)
            _register(trip.destination, trip.destination_stop_id or trip.destination)
            _register(trip.destination_stop_id, trip.destination_stop_id)

        for stop_id in self.turnaround_rules:
            _register(stop_id, stop_id)
        for from_stop, to_stop in self.deadhead_rules:
            _register(from_stop, from_stop)
            _register(to_stop, to_stop)

        for alias, targets in dict(self.location_aliases or {}).items():
            for target in tuple(targets or ()):
                _register(str(alias or ""), str(target or ""))

        self.location_aliases = {
            alias: tuple(sorted(targets))
            for alias, targets in alias_sets.items()
            if targets
        }

    def resolve_location_ids(self, raw: str) -> Tuple[str, ...]:
        text = str(raw or "").strip()
        if not text:
            return ()
        ordered: List[str] = []
        seen: set[str] = set()
        queue: List[str] = [text]
        while queue:
            current = queue.pop(0)
            current_text = str(current or "").strip()
            if not current_text or current_text in seen:
                continue
            seen.add(current_text)
            ordered.append(current_text)
            alias_targets = self.location_aliases.get(_normalize_location_key(current_text), ())
            for target in alias_targets:
                target_text = str(target or "").strip()
                if target_text and target_text not in seen:
                    queue.append(target_text)
        return tuple(ordered)

    def get_turnaround_min(self, stop_id: str) -> int:
        for candidate in self.resolve_location_ids(stop_id):
            rule = self.turnaround_rules.get(candidate)
            if rule is not None:
                return rule.min_turnaround_min
        return self.default_turnaround_min

    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        from_candidates = self.resolve_location_ids(from_stop)
        to_candidates = self.resolve_location_ids(to_stop)
        if not from_candidates:
            from_candidates = (str(from_stop or "").strip(),)
        if not to_candidates:
            to_candidates = (str(to_stop or "").strip(),)

        best: Optional[int] = None
        for from_candidate in from_candidates:
            for to_candidate in to_candidates:
                if from_candidate == to_candidate and from_candidate:
                    return 0
                rule = self.deadhead_rules.get((from_candidate, to_candidate))
                if rule is None:
                    continue
                travel_time = max(int(rule.travel_time_min or 0), 0)
                if best is None or travel_time < best:
                    best = travel_time
        return best if best is not None else 0

    def locations_equivalent(self, left: str, right: str) -> bool:
        left_candidates = self.resolve_location_ids(left)
        right_candidates = self.resolve_location_ids(right)
        if not left_candidates:
            left_candidates = (str(left or "").strip(),)
        if not right_candidates:
            right_candidates = (str(right or "").strip(),)
        return bool(
            {
                candidate
                for candidate in left_candidates
                if str(candidate or "").strip()
            }.intersection(
                {
                    candidate
                    for candidate in right_candidates
                    if str(candidate or "").strip()
                }
            )
        )

    def trips_by_id(self) -> Dict[str, Trip]:
        return {t.trip_id: t for t in self.trips}


def _normalize_location_key(raw: str) -> str:
    return unicodedata.normalize("NFKC", str(raw or "")).strip().lower()
