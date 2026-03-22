"""
src/dispatch/models.py

Core frozen dataclasses for the timetable-driven dispatch planning system.
These are dispatch-layer models, intentionally separate from src/schemas/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def hhmm_to_min(hhmm: str) -> int:
    """Convert 'HH:MM' string to integer minutes from midnight."""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


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

    def get_turnaround_min(self, stop_id: str) -> int:
        rule = self.turnaround_rules.get(stop_id)
        return rule.min_turnaround_min if rule else self.default_turnaround_min

    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        if from_stop == to_stop:
            return 0
        rule = self.deadhead_rules.get((from_stop, to_stop))
        return rule.travel_time_min if rule else 0

    def trips_by_id(self) -> Dict[str, Trip]:
        return {t.trip_id: t for t in self.trips}
