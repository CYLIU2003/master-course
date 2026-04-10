from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from src.dispatch.models import DutyLeg, VehicleDuty
from src.dispatch.route_band import fragment_transition_is_feasible

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

    def to_metadata(self) -> dict:
        return {
            "checked": bool(self.checked),
            "infeasible": bool(self.infeasible),
            "reason": self.reason,
            "trip_count": int(self.trip_count),
            "available_vehicle_count": int(self.available_vehicle_count),
            "relaxed_vehicle_lower_bound": int(self.relaxed_vehicle_lower_bound),
            "missing_vehicle_type_trip_ids": list(self.missing_vehicle_type_trip_ids),
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
    if service_coverage_mode != "strict" or not trips:
        return StrictCoveragePrecheckResult(
            checked=False,
            infeasible=False,
            trip_count=len(trips),
            available_vehicle_count=len(available_vehicles),
        )

    if not available_vehicles:
        return StrictCoveragePrecheckResult(
            checked=True,
            infeasible=True,
            reason="no_available_vehicles_for_strict_coverage",
            trip_count=len(trips),
            available_vehicle_count=0,
            relaxed_vehicle_lower_bound=1 if trips else 0,
            missing_vehicle_type_trip_ids=tuple(sorted(trip.trip_id for trip in trips)),
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
        return StrictCoveragePrecheckResult(
            checked=True,
            infeasible=True,
            reason="strict_trip_has_no_available_vehicle_type",
            trip_count=len(trips),
            available_vehicle_count=len(available_vehicles),
            relaxed_vehicle_lower_bound=len(available_vehicles) + 1,
            missing_vehicle_type_trip_ids=missing_type_trip_ids,
        )

    transition_graph = _build_relaxed_transition_graph(
        problem,
        trips,
        type_to_home_depots=type_to_home_depots,
    )
    matching_size = _hopcroft_karp_size(transition_graph)
    lower_bound = len(trips) - matching_size
    infeasible = lower_bound > len(available_vehicles)
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
) -> dict[str, Tuple[str, ...]]:
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
            to_duty = duty_by_trip_id[to_trip.trip_id]
            if _has_relaxed_transition(
                from_duty,
                to_duty,
                common_types=common_types,
                type_to_home_depots=type_to_home_depots,
                dispatch_context=problem.dispatch_context,
                fixed_route_band_mode=fixed_route_band_mode,
                allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            ):
                graph[from_trip.trip_id].append(to_trip.trip_id)
    return {trip_id: tuple(successors) for trip_id, successors in graph.items()}


def _has_relaxed_transition(
    from_duty: VehicleDuty,
    to_duty: VehicleDuty,
    *,
    common_types: Iterable[str],
    type_to_home_depots: Mapping[str, Tuple[str, ...]],
    dispatch_context: object,
    fixed_route_band_mode: bool,
    allow_same_day_depot_cycles: bool,
) -> bool:
    for vehicle_type in common_types:
        for home_depot_id in type_to_home_depots.get(str(vehicle_type), ("",)):
            if fragment_transition_is_feasible(
                from_duty,
                to_duty,
                home_depot_id=str(home_depot_id or ""),
                dispatch_context=dispatch_context,
                fixed_route_band_mode=fixed_route_band_mode,
                allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            ):
                return True
    return False


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
