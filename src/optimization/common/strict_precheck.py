from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from src.dispatch.models import DutyLeg, VehicleDuty
from src.dispatch.route_band import (
    FragmentTransitionDiagnostic,
    fragment_transition_diagnostic,
    trip_route_band_key,
)

from .problem import CanonicalOptimizationProblem, ProblemTrip, normalize_service_coverage_mode


@dataclass(frozen=True)
class StrictCoveragePrecheckResult:
    checked: bool
    infeasible: bool
    reason: str = ""
    trip_count: int = 0
    available_vehicle_count: int = 0
    relaxed_vehicle_lower_bound: int = 0
    missing_vehicle_type_trip_ids: Tuple[str, ...] = ()
    interval_only_lower_bound: int = 0
    interval_feasible_pair_count: int = 0
    dispatch_feasible_pair_count: int = 0
    blocked_transition_reason_counts: Dict[str, int] = field(default_factory=dict)
    blocked_transition_samples: Tuple[dict[str, object], ...] = ()
    dominant_blocked_transition_reason: str = ""
    diagnostic_message: str = ""

    def to_metadata(self) -> dict:
        return {
            "checked": bool(self.checked),
            "infeasible": bool(self.infeasible),
            "reason": self.reason,
            "trip_count": int(self.trip_count),
            "available_vehicle_count": int(self.available_vehicle_count),
            "relaxed_vehicle_lower_bound": int(self.relaxed_vehicle_lower_bound),
            "missing_vehicle_type_trip_ids": list(self.missing_vehicle_type_trip_ids),
            "interval_only_lower_bound": int(self.interval_only_lower_bound),
            "interval_feasible_pair_count": int(self.interval_feasible_pair_count),
            "dispatch_feasible_pair_count": int(self.dispatch_feasible_pair_count),
            "blocked_transition_reason_counts": dict(self.blocked_transition_reason_counts),
            "blocked_transition_samples": list(self.blocked_transition_samples),
            "dominant_blocked_transition_reason": self.dominant_blocked_transition_reason,
            "diagnostic_message": self.diagnostic_message,
        }


def evaluate_strict_coverage_precheck(
    problem: CanonicalOptimizationProblem,
) -> StrictCoveragePrecheckResult:
    """Prove obvious strict-coverage infeasibility before invoking a solver.

    The lower bound is intentionally relaxed: it ignores SOC, fuel, charger,
    and per-type fleet counts. If the relaxed vehicle path-cover still needs
    more vehicles than are available, the original strict problem cannot have
    a feasible incumbent.
    """

    service_coverage_mode = normalize_service_coverage_mode(
        getattr(problem.scenario, "service_coverage_mode", None)
        or problem.metadata.get("service_coverage_mode", "strict")
    )
    trips = tuple(problem.trips or ())
    available_vehicles = tuple(
        vehicle for vehicle in (problem.vehicles or ()) if bool(getattr(vehicle, "available", True))
    )
    interval_only_lower_bound = _interval_only_lower_bound(trips)
    if service_coverage_mode != "strict" or not trips:
        return StrictCoveragePrecheckResult(
            checked=False,
            infeasible=False,
            trip_count=len(trips),
            available_vehicle_count=len(available_vehicles),
            interval_only_lower_bound=interval_only_lower_bound,
        )

    if not available_vehicles:
        diagnostic_message = _strict_coverage_diagnostic_message(
            reason="no_available_vehicles_for_strict_coverage",
            trip_count=len(trips),
            available_vehicle_count=0,
            relaxed_vehicle_lower_bound=1 if trips else 0,
            interval_only_lower_bound=interval_only_lower_bound,
            missing_vehicle_type_trip_ids=(),
        )
        return StrictCoveragePrecheckResult(
            checked=True,
            infeasible=True,
            reason="no_available_vehicles_for_strict_coverage",
            trip_count=len(trips),
            available_vehicle_count=0,
            relaxed_vehicle_lower_bound=1 if trips else 0,
            missing_vehicle_type_trip_ids=tuple(sorted(trip.trip_id for trip in trips)),
            interval_only_lower_bound=interval_only_lower_bound,
            diagnostic_message=diagnostic_message,
        )

    type_to_home_depots = _available_home_depots_by_type(available_vehicles)
    available_types = set(type_to_home_depots)
    missing_type_trip_ids = tuple(
        sorted(
            trip.trip_id
            for trip in trips
            if not (_allowed_types(trip) & available_types)
        )
    )
    if missing_type_trip_ids:
        diagnostic_message = _strict_coverage_diagnostic_message(
            reason="strict_trip_has_no_available_vehicle_type",
            trip_count=len(trips),
            available_vehicle_count=len(available_vehicles),
            relaxed_vehicle_lower_bound=len(available_vehicles) + 1,
            interval_only_lower_bound=interval_only_lower_bound,
            missing_vehicle_type_trip_ids=missing_type_trip_ids,
        )
        return StrictCoveragePrecheckResult(
            checked=True,
            infeasible=True,
            reason="strict_trip_has_no_available_vehicle_type",
            trip_count=len(trips),
            available_vehicle_count=len(available_vehicles),
            relaxed_vehicle_lower_bound=len(available_vehicles) + 1,
            missing_vehicle_type_trip_ids=missing_type_trip_ids,
            interval_only_lower_bound=interval_only_lower_bound,
            diagnostic_message=diagnostic_message,
        )

    transition_graph, transition_audit = _build_relaxed_transition_graph(
        problem,
        trips,
        type_to_home_depots=type_to_home_depots,
    )
    matching_size = _hopcroft_karp_size(transition_graph)
    lower_bound = len(trips) - matching_size
    infeasible = lower_bound > len(available_vehicles)
    diagnostic_message = _strict_coverage_diagnostic_message(
        reason=(
            "strict_relaxed_path_cover_requires_more_vehicles_than_available"
            if infeasible
            else "not_proven_infeasible"
        ),
        trip_count=len(trips),
        available_vehicle_count=len(available_vehicles),
        relaxed_vehicle_lower_bound=lower_bound,
        interval_only_lower_bound=interval_only_lower_bound,
        missing_vehicle_type_trip_ids=(),
    )
    return StrictCoveragePrecheckResult(
        checked=True,
        infeasible=infeasible,
        reason=(
            "strict_relaxed_path_cover_requires_more_vehicles_than_available"
            if infeasible
            else "not_proven_infeasible"
        ),
        trip_count=len(trips),
        available_vehicle_count=len(available_vehicles),
        relaxed_vehicle_lower_bound=lower_bound,
        interval_only_lower_bound=interval_only_lower_bound,
        interval_feasible_pair_count=int(transition_audit.get("interval_feasible_pair_count") or 0),
        dispatch_feasible_pair_count=int(transition_audit.get("dispatch_feasible_pair_count") or 0),
        blocked_transition_reason_counts=dict(
            transition_audit.get("blocked_transition_reason_counts") or {}
        ),
        blocked_transition_samples=tuple(transition_audit.get("blocked_transition_samples") or ()),
        dominant_blocked_transition_reason=str(
            transition_audit.get("dominant_blocked_transition_reason") or ""
        ),
        diagnostic_message=diagnostic_message,
    )


def _interval_only_lower_bound(trips: Sequence[ProblemTrip]) -> int:
    if not trips:
        return 0
    events: list[tuple[int, int]] = []
    for trip in trips:
        departure_min = int(getattr(trip, "departure_min", 0) or 0)
        arrival_min = int(getattr(trip, "arrival_min", 0) or 0)
        events.append((departure_min, 1))
        events.append((arrival_min, -1))
    events.sort(key=lambda item: (item[0], item[1]))
    active = 0
    peak = 0
    for _minute, delta in events:
        active += delta
        if active > peak:
            peak = active
    return peak


def _strict_coverage_diagnostic_message(
    *,
    reason: str,
    trip_count: int,
    available_vehicle_count: int,
    relaxed_vehicle_lower_bound: int,
    interval_only_lower_bound: int,
    missing_vehicle_type_trip_ids: Sequence[str],
) -> str:
    if reason == "strict_trip_has_no_available_vehicle_type":
        return (
            "strict coverage is infeasible because "
            f"{len(missing_vehicle_type_trip_ids)} trips have no compatible available vehicle type."
        )
    if reason == "no_available_vehicles_for_strict_coverage":
        return (
            "strict coverage needs at least 1 vehicle, "
            "but the current fleet has 0 available vehicles."
        )
    if reason == "strict_relaxed_path_cover_requires_more_vehicles_than_available":
        return (
            "strict coverage needs at least "
            f"{relaxed_vehicle_lower_bound} vehicles, current fleet is {available_vehicle_count} "
            f"(interval-only lower bound: {interval_only_lower_bound}, trips: {trip_count})."
        )
    return (
        "strict coverage lower bound is "
        f"{relaxed_vehicle_lower_bound} vehicles, current fleet is {available_vehicle_count} "
        f"(interval-only lower bound: {interval_only_lower_bound}, trips: {trip_count})."
    )


def _available_home_depots_by_type(vehicles: Sequence[object]) -> dict[str, Tuple[str, ...]]:
    depots_by_type: dict[str, set[str]] = {}
    for vehicle in vehicles:
        vehicle_type = str(getattr(vehicle, "vehicle_type", "") or "").strip()
        if not vehicle_type:
            continue
        home_depot = str(getattr(vehicle, "home_depot_id", "") or "").strip()
        depots_by_type.setdefault(vehicle_type, set()).add(home_depot)
    return {
        vehicle_type: tuple(sorted(depots or {""}))
        for vehicle_type, depots in depots_by_type.items()
    }


def _allowed_types(trip: ProblemTrip) -> set[str]:
    return {
        str(vehicle_type or "").strip()
        for vehicle_type in tuple(getattr(trip, "allowed_vehicle_types", ()) or ())
        if str(vehicle_type or "").strip()
    }


def _build_relaxed_transition_graph(
    problem: CanonicalOptimizationProblem,
    trips: Sequence[ProblemTrip],
    *,
    type_to_home_depots: Mapping[str, Tuple[str, ...]],
) -> tuple[dict[str, Tuple[str, ...]], dict[str, object]]:
    ordered = tuple(
        sorted(
            trips,
            key=lambda trip: (
                int(trip.departure_min),
                int(trip.arrival_min),
                str(trip.trip_id),
            ),
        )
    )
    duty_by_trip_id = {
        trip.trip_id: VehicleDuty(
            duty_id=trip.trip_id,
            vehicle_type=next(iter(sorted(_allowed_types(trip))), ""),
            legs=(DutyLeg(trip=trip, deadhead_from_prev_min=0),),
        )
        for trip in ordered
    }
    allowed_by_trip_id = {
        trip.trip_id: _allowed_types(trip).intersection(type_to_home_depots.keys())
        for trip in ordered
    }
    fixed_route_band_mode = bool(problem.metadata.get("fixed_route_band_mode", False))
    allow_same_day_depot_cycles = bool(
        problem.metadata.get(
            "allow_same_day_depot_cycles",
            getattr(problem.scenario, "allow_same_day_depot_cycles", True),
        )
    )

    graph: dict[str, list[str]] = {trip.trip_id: [] for trip in ordered}
    blocked_transition_reason_counts: Counter[str] = Counter()
    blocked_transition_samples: list[dict[str, object]] = []
    interval_feasible_pair_count = 0
    dispatch_feasible_pair_count = 0
    sample_limit = 20
    for index, from_trip in enumerate(ordered):
        from_allowed = allowed_by_trip_id[from_trip.trip_id]
        if not from_allowed:
            continue
        from_duty = duty_by_trip_id[from_trip.trip_id]
        for to_trip in ordered[index + 1 :]:
            if int(to_trip.departure_min) < int(from_trip.arrival_min):
                continue
            common_types = from_allowed.intersection(allowed_by_trip_id[to_trip.trip_id])
            if not common_types:
                continue
            interval_feasible_pair_count += 1
            to_duty = duty_by_trip_id[to_trip.trip_id]
            transition = _transition_diagnostic_for_common_types(
                from_duty,
                to_duty,
                common_types=common_types,
                type_to_home_depots=type_to_home_depots,
                dispatch_context=problem.dispatch_context,
                fixed_route_band_mode=fixed_route_band_mode,
                allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            )
            if transition.feasible:
                graph[from_trip.trip_id].append(to_trip.trip_id)
                dispatch_feasible_pair_count += 1
                continue
            blocked_transition_reason_counts[transition.reason_code or "unknown"] += 1
            if len(blocked_transition_samples) < sample_limit:
                from_legs = tuple(getattr(from_duty, "legs", ()) or ())
                to_legs = tuple(getattr(to_duty, "legs", ()) or ())
                from_leg = from_legs[-1] if from_legs else None
                to_leg = to_legs[0] if to_legs else None
                from_trip_like = getattr(from_leg, "trip", None)
                to_trip_like = getattr(to_leg, "trip", None)
                blocked_transition_samples.append(
                    {
                        "from_trip_id": str(from_trip.trip_id),
                        "to_trip_id": str(to_trip.trip_id),
                        "from_route_code": str(
                            getattr(from_trip_like, "route_id", "") or getattr(from_trip_like, "route_family_code", "") or ""
                        ),
                        "to_route_code": str(
                            getattr(to_trip_like, "route_id", "") or getattr(to_trip_like, "route_family_code", "") or ""
                        ),
                        "from_route_family_code": str(getattr(from_trip_like, "route_family_code", "") or ""),
                        "to_route_family_code": str(getattr(to_trip_like, "route_family_code", "") or ""),
                        "from_direction": str(getattr(from_trip_like, "direction", "") or ""),
                        "to_direction": str(getattr(to_trip_like, "direction", "") or ""),
                        "from_route_variant_type": str(getattr(from_trip_like, "route_variant_type", "") or ""),
                        "to_route_variant_type": str(getattr(to_trip_like, "route_variant_type", "") or ""),
                        "from_stop": str(getattr(from_trip_like, "destination_stop_id", "") or getattr(from_trip_like, "destination", "") or ""),
                        "to_stop": str(getattr(to_trip_like, "origin_stop_id", "") or getattr(to_trip_like, "origin", "") or ""),
                        "from_arrival": int(getattr(from_trip_like, "arrival_min", 0) or 0),
                        "to_departure": int(getattr(to_trip_like, "departure_min", 0) or 0),
                        "deadhead_lookup_key": f"{getattr(from_trip_like, 'destination_stop_id', '') or getattr(from_trip_like, 'destination', '')}->{getattr(to_trip_like, 'origin_stop_id', '') or getattr(to_trip_like, 'origin', '')}",
                        "route_band_key_from": trip_route_band_key(from_trip_like),
                        "route_band_key_to": trip_route_band_key(to_trip_like),
                        "blocked_reason": str(transition.reason_code or "unknown"),
                        "direct_ok": bool(transition.direct_ok),
                        "depot_reset_ok": bool(transition.depot_reset_ok),
                        "route_band_blocked": bool(transition.route_band_blocked),
                        "deadhead_missing": bool(transition.deadhead_missing),
                        "location_alias_missing": bool(transition.location_alias_missing),
                    }
                )
    audit = {
        "interval_feasible_pair_count": interval_feasible_pair_count,
        "dispatch_feasible_pair_count": dispatch_feasible_pair_count,
        "blocked_transition_reason_counts": dict(sorted(blocked_transition_reason_counts.items())),
        "blocked_transition_samples": blocked_transition_samples,
        "dominant_blocked_transition_reason": _dominant_reason(blocked_transition_reason_counts),
    }
    return ({trip_id: tuple(successors) for trip_id, successors in graph.items()}, audit)


def _dominant_reason(reason_counts: Counter[str]) -> str:
    if not reason_counts:
        return ""
    return max(
        reason_counts.items(),
        key=lambda item: (int(item[1]), str(item[0])),
    )[0]


def _transition_diagnostic_for_common_types(
    from_duty: VehicleDuty,
    to_duty: VehicleDuty,
    *,
    common_types: Iterable[str],
    type_to_home_depots: Mapping[str, Tuple[str, ...]],
    dispatch_context: object,
    fixed_route_band_mode: bool,
    allow_same_day_depot_cycles: bool,
) -> FragmentTransitionDiagnostic:
    reason_counts: Counter[str] = Counter()
    for vehicle_type in common_types:
        for home_depot_id in type_to_home_depots.get(str(vehicle_type), ("",)):
            diagnostic = fragment_transition_diagnostic(
                from_duty,
                to_duty,
                home_depot_id=str(home_depot_id or ""),
                dispatch_context=dispatch_context,
                fixed_route_band_mode=fixed_route_band_mode,
                allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            )
            if diagnostic.feasible:
                return diagnostic
            reason_counts[diagnostic.reason_code or "unknown"] += 1
    return FragmentTransitionDiagnostic(
        feasible=False,
        reason_code=_dominant_reason(reason_counts) or "unknown",
        direct_ok=False,
        depot_reset_ok=False,
        route_band_blocked="route_band_blocked" in reason_counts,
        deadhead_missing="deadhead_missing" in reason_counts,
        location_alias_missing="location_alias_missing" in reason_counts,
    )


def _hopcroft_karp_size(graph: Mapping[str, Sequence[str]]) -> int:
    left_nodes = tuple(sorted(graph.keys()))
    right_nodes = tuple(sorted({node for successors in graph.values() for node in successors}))
    pair_left: Dict[str, str | None] = {node: None for node in left_nodes}
    pair_right: Dict[str, str | None] = {node: None for node in right_nodes}
    distance: Dict[str, int] = {}

    def bfs() -> bool:
        queue: list[str] = []
        found_free = False
        for node in left_nodes:
            if pair_left[node] is None:
                distance[node] = 0
                queue.append(node)
            else:
                distance[node] = -1
        head = 0
        while head < len(queue):
            node = queue[head]
            head += 1
            for successor in graph.get(node, ()):
                paired = pair_right.get(successor)
                if paired is None:
                    found_free = True
                elif distance.get(paired, -1) < 0:
                    distance[paired] = distance[node] + 1
                    queue.append(paired)
        return found_free

    def dfs(node: str) -> bool:
        for successor in graph.get(node, ()):
            paired = pair_right.get(successor)
            if paired is None or (
                distance.get(paired, -1) == distance[node] + 1 and dfs(paired)
            ):
                pair_left[node] = successor
                pair_right[successor] = node
                return True
        distance[node] = -1
        return False

    matching = 0
    while bfs():
        for node in left_nodes:
            if pair_left[node] is None and dfs(node):
                matching += 1
    return matching
