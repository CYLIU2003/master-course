from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Protocol, Tuple

try:
    import gurobipy as gp
    from gurobipy import GRB

    _GUROBI_AVAILABLE = True
except Exception:  # pragma: no cover
    gp = None
    GRB = None
    _GUROBI_AVAILABLE = False

from src.dispatch.models import DutyLeg, VehicleDuty

from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
)


@dataclass(frozen=True)
class MILPSolverOutcome:
    solver_status: str
    used_backend: str
    supports_exact_milp: bool


class SolverAdapter(Protocol):
    backend_name: str

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> Tuple[MILPSolverOutcome, AssignmentPlan]:
        ...


class DispatchBaselineMILPAdapter:
    backend_name = "dispatch_baseline"

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> Tuple[MILPSolverOutcome, AssignmentPlan]:
        plan = problem.baseline_plan or AssignmentPlan()
        return (
            MILPSolverOutcome(
                solver_status="baseline_feasible",
                used_backend=self.backend_name,
                supports_exact_milp=False,
            ),
            plan,
        )


class GurobiMILPAdapter:
    backend_name = "gurobi"

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> Tuple[MILPSolverOutcome, AssignmentPlan]:
        if not _GUROBI_AVAILABLE:
            baseline = problem.baseline_plan or AssignmentPlan()
            return (
                MILPSolverOutcome(
                    solver_status="gurobi_unavailable_baseline",
                    used_backend="dispatch_baseline",
                    supports_exact_milp=False,
                ),
                baseline,
            )

        model = gp.Model("optimization_milp_adapter")
        model.Params.OutputFlag = 0
        model.Params.TimeLimit = max(1, int(config.time_limit_sec))
        model.Params.MIPGap = max(float(config.mip_gap), 0.0)
        model.Params.Seed = int(config.random_seed)

        trip_by_id = problem.trip_by_id()
        dispatch_trip_by_id = problem.dispatch_context.trips_by_id()

        y: Dict[Tuple[str, str], gp.Var] = {}
        for vehicle in problem.vehicles:
            for trip in problem.trips:
                if vehicle.vehicle_type in trip.allowed_vehicle_types:
                    y[(vehicle.vehicle_id, trip.trip_id)] = model.addVar(
                        vtype=GRB.BINARY,
                        name=f"y[{vehicle.vehicle_id},{trip.trip_id}]",
                    )

        unserved: Dict[str, gp.Var] = {
            trip.trip_id: model.addVar(vtype=GRB.BINARY, name=f"u[{trip.trip_id}]")
            for trip in problem.trips
        }

        used_vehicle: Dict[str, gp.Var] = {
            vehicle.vehicle_id: model.addVar(vtype=GRB.BINARY, name=f"z[{vehicle.vehicle_id}]")
            for vehicle in problem.vehicles
        }

        # Each trip must be assigned exactly once or marked as unserved.
        for trip in problem.trips:
            assign_terms = [
                y[(vehicle.vehicle_id, trip.trip_id)]
                for vehicle in problem.vehicles
                if (vehicle.vehicle_id, trip.trip_id) in y
            ]
            model.addConstr(gp.quicksum(assign_terms) + unserved[trip.trip_id] == 1)

        # Vehicle-use linkage.
        for (vehicle_id, trip_id), var in y.items():
            model.addConstr(var <= used_vehicle[vehicle_id])

        # Pairwise incompatibility on each vehicle.
        for vehicle in problem.vehicles:
            eligible = [trip for trip in problem.trips if (vehicle.vehicle_id, trip.trip_id) in y]
            for i in range(len(eligible)):
                trip_i = eligible[i]
                for j in range(i + 1, len(eligible)):
                    trip_j = eligible[j]
                    i_to_j = trip_j.trip_id in problem.feasible_connections.get(trip_i.trip_id, ())
                    j_to_i = trip_i.trip_id in problem.feasible_connections.get(trip_j.trip_id, ())
                    if not i_to_j and not j_to_i:
                        model.addConstr(
                            y[(vehicle.vehicle_id, trip_i.trip_id)]
                            + y[(vehicle.vehicle_id, trip_j.trip_id)]
                            <= 1
                        )

        bev_ids = [
            vehicle.vehicle_id
            for vehicle in problem.vehicles
            if vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}
        ]
        slot_indices = sorted({slot.slot_index for slot in problem.price_slots})
        timestep_h = max(problem.scenario.timestep_min, 1) / 60.0

        c_var: Dict[Tuple[str, int], gp.Var] = {}
        d_var: Dict[Tuple[str, int], gp.Var] = {}
        s_var: Dict[Tuple[str, int], gp.Var] = {}

        if bev_ids and slot_indices:
            for vehicle in problem.vehicles:
                if vehicle.vehicle_id not in bev_ids:
                    continue
                cap = max(vehicle.battery_capacity_kwh or 300.0, 1.0)
                reserve = vehicle.reserve_soc
                if reserve is None:
                    soc_min = 0.15 * cap
                elif reserve <= 1.0:
                    soc_min = reserve * cap
                else:
                    soc_min = reserve

                charge_max_kw = self._charge_power_max_kw(problem, vehicle.vehicle_type)
                discharge_max_kw = self._discharge_power_max_kw(problem, vehicle.vehicle_type)

                for slot_idx in slot_indices:
                    c_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(
                        lb=0.0,
                        ub=charge_max_kw,
                        vtype=GRB.CONTINUOUS,
                        name=f"c[{vehicle.vehicle_id},{slot_idx}]",
                    )
                    d_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(
                        lb=0.0,
                        ub=discharge_max_kw,
                        vtype=GRB.CONTINUOUS,
                        name=f"d[{vehicle.vehicle_id},{slot_idx}]",
                    )
                    s_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(
                        lb=soc_min,
                        ub=cap,
                        vtype=GRB.CONTINUOUS,
                        name=f"s[{vehicle.vehicle_id},{slot_idx}]",
                    )

                initial_soc = vehicle.initial_soc
                if initial_soc is None:
                    initial_kwh = 0.8 * cap
                elif initial_soc <= 1.0:
                    initial_kwh = initial_soc * cap
                else:
                    initial_kwh = initial_soc
                initial_kwh = min(max(initial_kwh, soc_min), cap)
                first_slot = slot_indices[0]
                model.addConstr(s_var[(vehicle.vehicle_id, first_slot)] == initial_kwh)

                for pos in range(len(slot_indices) - 1):
                    slot_idx = slot_indices[pos]
                    next_slot_idx = slot_indices[pos + 1]
                    trip_energy_expr = gp.quicksum(
                        trip.energy_kwh * y[(vehicle.vehicle_id, trip.trip_id)]
                        for trip in problem.trips
                        if (vehicle.vehicle_id, trip.trip_id) in y
                        and self._slot_index(problem, trip.departure_min) == slot_idx
                    )
                    model.addConstr(
                        s_var[(vehicle.vehicle_id, next_slot_idx)]
                        == s_var[(vehicle.vehicle_id, slot_idx)]
                        + 0.95 * c_var[(vehicle.vehicle_id, slot_idx)] * timestep_h
                        - d_var[(vehicle.vehicle_id, slot_idx)] * timestep_h / 0.95
                        - trip_energy_expr
                    )

            if problem.chargers:
                total_kw = sum(
                    charger.power_kw * max(charger.simultaneous_ports, 1)
                    for charger in problem.chargers
                )
                for slot_idx in slot_indices:
                    model.addConstr(
                        gp.quicksum(c_var[(vehicle_id, slot_idx)] for vehicle_id in bev_ids)
                        <= total_kw
                    )

        avg_price = (
            sum(slot.grid_buy_yen_per_kwh for slot in problem.price_slots) / len(problem.price_slots)
            if problem.price_slots
            else 0.0
        )
        unserved_penalty_weight = max(problem.objective_weights.unserved, 10000.0)

        objective = gp.LinExpr()
        for (vehicle_id, trip_id), var in y.items():
            vehicle = next((v for v in problem.vehicles if v.vehicle_id == vehicle_id), None)
            trip = trip_by_id.get(trip_id)
            if vehicle is None or trip is None:
                continue
            objective += (vehicle.fixed_use_cost_jpy * 0.05 + trip.energy_kwh * avg_price) * var
        for vehicle in problem.vehicles:
            objective += vehicle.fixed_use_cost_jpy * used_vehicle[vehicle.vehicle_id]
        for trip in problem.trips:
            objective += unserved_penalty_weight * unserved[trip.trip_id]

        model.setObjective(objective, GRB.MINIMIZE)
        model.optimize()

        status_map = {
            GRB.OPTIMAL: "optimal",
            GRB.TIME_LIMIT: "time_limit",
            GRB.SUBOPTIMAL: "suboptimal",
            GRB.INFEASIBLE: "infeasible",
            GRB.INF_OR_UNBD: "inf_or_unbd",
            GRB.UNBOUNDED: "unbounded",
        }
        solver_status = status_map.get(model.Status, f"status_{model.Status}")

        if model.SolCount <= 0:
            empty = AssignmentPlan(
                duties=(),
                charging_slots=(),
                served_trip_ids=(),
                unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips)),
                metadata={"source": "milp_gurobi", "status": solver_status},
            )
            return (
                MILPSolverOutcome(
                    solver_status=solver_status,
                    used_backend=self.backend_name,
                    supports_exact_milp=True,
                ),
                empty,
            )

        duties: List[VehicleDuty] = []
        served_trip_ids: List[str] = []

        for vehicle in problem.vehicles:
            assigned_trip_ids = [
                trip.trip_id
                for trip in problem.trips
                if (vehicle.vehicle_id, trip.trip_id) in y
                and y[(vehicle.vehicle_id, trip.trip_id)].X > 0.5
            ]
            if not assigned_trip_ids:
                continue

            assigned_trip_ids.sort(key=lambda trip_id: trip_by_id[trip_id].departure_min)
            legs: List[DutyLeg] = []
            prev_trip = None
            for trip_id in assigned_trip_ids:
                dispatch_trip = dispatch_trip_by_id.get(trip_id)
                if dispatch_trip is None:
                    continue
                deadhead = 0
                if prev_trip is not None:
                    deadhead = problem.dispatch_context.get_deadhead_min(
                        prev_trip.destination,
                        dispatch_trip.origin,
                    )
                legs.append(DutyLeg(trip=dispatch_trip, deadhead_from_prev_min=deadhead))
                prev_trip = dispatch_trip
                served_trip_ids.append(trip_id)

            if legs:
                duties.append(
                    VehicleDuty(
                        duty_id=f"milp_{vehicle.vehicle_id}",
                        vehicle_type=vehicle.vehicle_type,
                        legs=tuple(legs),
                    )
                )

        served_set = set(served_trip_ids)
        unserved_trip_ids = sorted(trip.trip_id for trip in problem.trips if trip.trip_id not in served_set)

        plan = AssignmentPlan(
            duties=tuple(duties),
            charging_slots=(),
            served_trip_ids=tuple(sorted(served_set)),
            unserved_trip_ids=tuple(unserved_trip_ids),
            metadata={
                "source": "milp_gurobi",
                "status": solver_status,
                "objective_value": float(model.ObjVal),
            },
        )
        return (
            MILPSolverOutcome(
                solver_status=solver_status,
                used_backend=self.backend_name,
                supports_exact_milp=True,
            ),
            plan,
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

    def _charge_power_max_kw(self, problem: CanonicalOptimizationProblem, vehicle_type: str) -> float:
        vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle_type), None)
        if vt and vt.charge_power_max_kw is not None:
            return max(vt.charge_power_max_kw, 0.0)
        if problem.chargers:
            return max(charger.power_kw for charger in problem.chargers)
        return 50.0

    def _discharge_power_max_kw(self, problem: CanonicalOptimizationProblem, vehicle_type: str) -> float:
        vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle_type), None)
        if vt and vt.discharge_power_max_kw is not None:
            return max(vt.discharge_power_max_kw, 0.0)
        return self._charge_power_max_kw(problem, vehicle_type)
