from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    normalize_service_coverage_mode,
)


@dataclass(frozen=True)
class MILPVariableDefinition:
    name: str
    var_type: str
    index: Tuple[str, ...]
    lower_bound: float = 0.0
    upper_bound: float | None = None
    description: str = ""


@dataclass(frozen=True)
class MILPConstraintDefinition:
    name: str
    sense: str
    rhs: float | str
    terms: Tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class MILPModelDescription:
    variable_counts: Dict[str, int]
    constraint_counts: Dict[str, int]
    variables: Tuple[MILPVariableDefinition, ...] = ()
    constraints: Tuple[MILPConstraintDefinition, ...] = ()
    objective_terms: Tuple[str, ...] = ()


class MILPModelBuilder:
    def enumerate_assignment_pairs(
        self,
        problem: CanonicalOptimizationProblem,
    ) -> List[Tuple[str, str]]:
        pairs: List[Tuple[str, str]] = []
        for vehicle in problem.vehicles:
            # Skip unavailable vehicles
            if not getattr(vehicle, "available", True):
                continue
            for trip in problem.trips:
                if vehicle.vehicle_type in trip.allowed_vehicle_types:
                    pairs.append((vehicle.vehicle_id, trip.trip_id))
        return pairs

    def enumerate_arc_pairs(
        self,
        problem: CanonicalOptimizationProblem,
        trip_by_id: Dict[str, object],
    ) -> List[Tuple[str, str, str]]:
        pairs: List[Tuple[str, str, str]] = []
        fixed_route_band_mode = bool(problem.metadata.get("fixed_route_band_mode", False))
        max_successors_per_trip = self._safe_positive_int(
            problem.metadata.get("milp_max_successors_per_trip"),
            default=999999,
        )
        dispatch_trip_by_id = problem.dispatch_context.trips_by_id()
        route_band_by_trip_id = {
            trip.trip_id: str(
                getattr(dispatch_trip_by_id.get(trip.trip_id), "route_family_code", "")
                or trip.route_id
            )
            for trip in problem.trips
        }
        for vehicle in problem.vehicles:
            if not getattr(vehicle, "available", True):
                continue
            for trip_i in problem.trips:
                if vehicle.vehicle_type not in trip_i.allowed_vehicle_types:
                    continue
                candidate_successors = [
                    trip_j_id
                    for trip_j_id in problem.feasible_connections.get(trip_i.trip_id, ())
                    if not fixed_route_band_mode
                    or route_band_by_trip_id.get(trip_i.trip_id) == route_band_by_trip_id.get(trip_j_id)
                ]
                candidate_successors.sort(
                    key=lambda trip_j_id: (
                        getattr(trip_by_id.get(trip_j_id), "departure_min", 10**9),
                        getattr(trip_by_id.get(trip_j_id), "arrival_min", 10**9),
                        trip_j_id,
                    )
                )
                for trip_j_id in candidate_successors[:max_successors_per_trip]:
                    trip_j = trip_by_id.get(trip_j_id)
                    if trip_j is None:
                        continue
                    if vehicle.vehicle_type not in getattr(trip_j, "allowed_vehicle_types", ()):  # type-safe edge
                        continue
                    pairs.append((vehicle.vehicle_id, trip_i.trip_id, trip_j_id))
        return pairs

    def _safe_positive_int(self, value: object, *, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def build(self, problem: CanonicalOptimizationProblem) -> MILPModelDescription:
        variables: List[MILPVariableDefinition] = []
        constraints: List[MILPConstraintDefinition] = []
        service_coverage_mode = normalize_service_coverage_mode(
            getattr(problem.scenario, "service_coverage_mode", None)
            or problem.metadata.get("service_coverage_mode", "strict")
        )
        trip_by_id = problem.trip_by_id()
        slot_indices = sorted({slot.slot_index for slot in problem.price_slots})
        slot_pos_map = {slot_index: pos for pos, slot_index in enumerate(slot_indices)}
        timestep_h = max(problem.scenario.timestep_min, 1) / 60.0
        bev_vehicle_ids = [
            vehicle.vehicle_id
            for vehicle in problem.vehicles
            if vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}
        ]

        assignment_pairs = self.enumerate_assignment_pairs(problem)
        arc_pairs = self.enumerate_arc_pairs(problem, trip_by_id)
        for vehicle_id, trip_id in assignment_pairs:
            variables.append(
                MILPVariableDefinition(
                    name=f"y[{vehicle_id},{trip_id}]",
                    var_type="BINARY",
                    index=(vehicle_id, trip_id),
                    description="vehicle-trip assignment",
                )
            )
        for vehicle_id, trip_i_id, trip_j_id in arc_pairs:
            variables.append(
                MILPVariableDefinition(
                    name=f"x[{vehicle_id},{trip_i_id},{trip_j_id}]",
                    var_type="BINARY",
                    index=(vehicle_id, trip_i_id, trip_j_id),
                    description="vehicle uses feasible trip connection arc",
                )
            )

        for trip in problem.trips:
            variables.append(
                MILPVariableDefinition(
                    name=f"u[{trip.trip_id}]",
                    var_type="BINARY",
                    index=(trip.trip_id,),
                    description="trip left unserved with penalty",
                )
            )

        for vehicle_id in bev_vehicle_ids:
            for slot in problem.price_slots:
                variables.extend(
                    [
                        MILPVariableDefinition(
                            name=f"c[{vehicle_id},{slot.slot_index}]",
                            var_type="CONTINUOUS",
                            index=(vehicle_id, str(slot.slot_index)),
                            description="charging power",
                        ),
                        MILPVariableDefinition(
                            name=f"d[{vehicle_id},{slot.slot_index}]",
                            var_type="CONTINUOUS",
                            index=(vehicle_id, str(slot.slot_index)),
                            description="discharging power",
                        ),
                        MILPVariableDefinition(
                            name=f"s[{vehicle_id},{slot.slot_index}]",
                            var_type="CONTINUOUS",
                            index=(vehicle_id, str(slot.slot_index)),
                            description="state of charge at slot end",
                        ),
                    ]
                )

        for slot in problem.price_slots:
            variables.extend(
                [
                    MILPVariableDefinition(
                        name=f"p_grid_plus[{slot.slot_index}]",
                        var_type="CONTINUOUS",
                        index=(str(slot.slot_index),),
                        description="grid import",
                    ),
                    MILPVariableDefinition(
                        name=f"p_grid_minus[{slot.slot_index}]",
                        var_type="CONTINUOUS",
                        index=(str(slot.slot_index),),
                        description="grid export",
                    ),
                    MILPVariableDefinition(
                        name=f"p_pv[{slot.slot_index}]",
                        var_type="CONTINUOUS",
                        index=(str(slot.slot_index),),
                        description="pv used on-site",
                    ),
                ]
            )

        for trip in problem.trips:
            eligible_terms = tuple(
                f"y[{vehicle_id},{trip.trip_id}]"
                for vehicle_id, trip_id in assignment_pairs
                if trip_id == trip.trip_id
            )
            cover_terms = eligible_terms
            cover_description = "each trip covered exactly once"
            if service_coverage_mode == "penalized":
                cover_terms = eligible_terms + (f"u[{trip.trip_id}]",)
                cover_description = "each trip covered exactly once or marked unserved"
            constraints.append(
                MILPConstraintDefinition(
                    name=f"cover_trip[{trip.trip_id}]",
                    sense="EQ",
                    rhs=1.0,
                    terms=cover_terms,
                    description=cover_description,
                )
            )

        for vehicle in problem.vehicles:
            for trip in problem.trips:
                if vehicle.vehicle_type not in trip.allowed_vehicle_types:
                    continue
                incoming = tuple(
                    f"x[{vehicle.vehicle_id},{from_trip},{trip.trip_id}]"
                    for _vehicle_id, from_trip, to_trip in arc_pairs
                    if _vehicle_id == vehicle.vehicle_id and to_trip == trip.trip_id
                )
                outgoing = tuple(
                    f"x[{vehicle.vehicle_id},{trip.trip_id},{to_trip}]"
                    for _vehicle_id, from_trip, to_trip in arc_pairs
                    if _vehicle_id == vehicle.vehicle_id and from_trip == trip.trip_id
                )
                constraints.extend(
                    [
                        MILPConstraintDefinition(
                            name=f"flow_in[{vehicle.vehicle_id},{trip.trip_id}]",
                            sense="LE",
                            rhs=f"y[{vehicle.vehicle_id},{trip.trip_id}]",
                            terms=incoming,
                            description="incoming arc count bounded by assignment",
                        ),
                        MILPConstraintDefinition(
                            name=f"flow_out[{vehicle.vehicle_id},{trip.trip_id}]",
                            sense="LE",
                            rhs=f"y[{vehicle.vehicle_id},{trip.trip_id}]",
                            terms=outgoing,
                            description="outgoing arc count bounded by assignment",
                        ),
                    ]
                )

        for vehicle in problem.vehicles:
            if vehicle.vehicle_id not in bev_vehicle_ids:
                continue
            for pos in range(len(slot_indices) - 1):
                slot_idx = slot_indices[pos]
                next_slot_idx = slot_indices[pos + 1]
                trip_energy_terms = tuple(
                    f"-{trip.energy_kwh}*y[{vehicle.vehicle_id},{trip.trip_id}]"
                    for trip in problem.trips
                    if (vehicle.vehicle_id, trip.trip_id) in assignment_pairs
                    and slot_pos_map.get(self._slot_index(problem, trip.departure_min)) == pos
                )
                constraints.append(
                    MILPConstraintDefinition(
                        name=f"soc_transition[{vehicle.vehicle_id},{slot_idx}->{next_slot_idx}]",
                        sense="EQ",
                        rhs=0.0,
                        terms=(
                            f"s[{vehicle.vehicle_id},{next_slot_idx}]",
                            f"-s[{vehicle.vehicle_id},{slot_idx}]",
                            f"-0.95*{timestep_h}*c[{vehicle.vehicle_id},{slot_idx}]",
                            f"+{timestep_h / 0.95}*d[{vehicle.vehicle_id},{slot_idx}]",
                        )
                        + trip_energy_terms,
                        description="slot-based SOC dynamics with assignment-linked trip energy",
                    )
                )

        if problem.chargers:
            total_power = sum(charger.power_kw * charger.simultaneous_ports for charger in problem.chargers)
            for slot in problem.price_slots:
                charge_terms = tuple(
                    f"c[{vehicle_id},{slot.slot_index}]"
                    for vehicle_id in bev_vehicle_ids
                )
                constraints.append(
                    MILPConstraintDefinition(
                        name=f"charger_capacity[{slot.slot_index}]",
                        sense="LE",
                        rhs=total_power,
                        terms=charge_terms,
                        description="aggregate charger power capacity",
                    )
                )

        if problem.depots:
            for depot in problem.depots:
                for slot in problem.price_slots:
                    constraints.append(
                        MILPConstraintDefinition(
                            name=f"depot_import_limit[{depot.depot_id},{slot.slot_index}]",
                            sense="LE",
                            rhs=depot.import_limit_kw,
                            terms=(f"p_grid_plus[{slot.slot_index}]",),
                            description="depot grid import limit",
                        )
                    )

        for slot in problem.pv_slots:
            constraints.append(
                MILPConstraintDefinition(
                    name=f"pv_limit[{slot.slot_index}]",
                    sense="LE",
                    rhs=slot.pv_available_kw,
                    terms=(f"p_pv[{slot.slot_index}]",),
                    description="PV self-consumption upper bound",
                )
            )

        objective_terms = tuple(
            [
                "energy_cost = sum_t price_t * p_grid_plus[t]",
                "revenue_credit = sum_t sell_price_t * p_grid_minus[t]",
                "vehicle_cost = sum_vi fixed_vehicle_cost * y[v,i]",
                "unserved_penalty = sum_i penalty_i * u[i]",
                "deviation_cost = weighted plan delta",
            ]
        )

        return MILPModelDescription(
            variable_counts={
                "assignment": len(assignment_pairs),
                "connection_arc": len(arc_pairs),
                "unserved": len(problem.trips),
                "charging": len(bev_vehicle_ids) * len(problem.price_slots),
                "discharging": len(bev_vehicle_ids) * len(problem.price_slots),
                "soc": len(bev_vehicle_ids) * len(problem.price_slots),
                "grid_import": len(problem.price_slots),
                "grid_export": len(problem.price_slots),
                "pv_use": len(problem.price_slots),
            },
            constraint_counts={
                "cover_each_trip": len(problem.trips),
                "flow_in": len(assignment_pairs),
                "flow_out": len(assignment_pairs),
                "soc_transition": len(bev_vehicle_ids) * max(len(slot_indices) - 1, 0),
                "charger_capacity": len(problem.price_slots) if problem.chargers else 0,
                "depot_import_limit": len(problem.depots) * len(problem.price_slots),
                "pv_limit": len(problem.pv_slots),
            },
            variables=tuple(variables),
            constraints=tuple(constraints),
            objective_terms=objective_terms,
        )

    def _slot_index(self, problem: CanonicalOptimizationProblem, departure_min: int) -> int:
        timestep_min = max(problem.scenario.timestep_min, 1)
        if not problem.scenario.horizon_start:
            return departure_min // timestep_min
        try:
            hh, mm = problem.scenario.horizon_start.split(":")
            start_min = int(hh) * 60 + int(mm)
        except ValueError:
            return departure_min // timestep_min
        adjusted = departure_min
        if adjusted < start_min:
            adjusted += 24 * 60
        return (adjusted - start_min) // timestep_min
