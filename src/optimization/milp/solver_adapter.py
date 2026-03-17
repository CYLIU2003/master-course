from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, Tuple

try:
    import gurobipy as gp
    from gurobipy import GRB

    _GUROBI_AVAILABLE = True
except Exception:  # pragma: no cover
    gp = None
    GRB = None
    _GUROBI_AVAILABLE = False

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.milp.model_builder import MILPModelBuilder

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

        builder = MILPModelBuilder()
        trip_by_id = problem.trip_by_id()
        dispatch_trip_by_id = problem.dispatch_context.trips_by_id()
        assignment_pairs = builder.enumerate_assignment_pairs(problem)
        arc_pairs = builder.enumerate_arc_pairs(problem, trip_by_id)

        y: Dict[Tuple[str, str], Any] = {}
        for vehicle_id, trip_id in assignment_pairs:
            y[(vehicle_id, trip_id)] = model.addVar(vtype=GRB.BINARY)

        x: Dict[Tuple[str, str, str], Any] = {
            (vehicle_id, from_trip_id, to_trip_id): model.addVar(vtype=GRB.BINARY)
            for vehicle_id, from_trip_id, to_trip_id in arc_pairs
        }

        start_arc: Dict[Tuple[str, str], Any] = {
            (vehicle_id, trip_id): model.addVar(vtype=GRB.BINARY)
            for vehicle_id, trip_id in assignment_pairs
        }
        end_arc: Dict[Tuple[str, str], Any] = {
            (vehicle_id, trip_id): model.addVar(vtype=GRB.BINARY)
            for vehicle_id, trip_id in assignment_pairs
        }

        unserved: Dict[str, Any] = {
            trip.trip_id: model.addVar(vtype=GRB.BINARY)
            for trip in problem.trips
        }

        used_vehicle: Dict[str, Any] = {
            vehicle.vehicle_id: model.addVar(vtype=GRB.BINARY)
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

        outgoing_by_node: Dict[Tuple[str, str], List[Any]] = {}
        incoming_by_node: Dict[Tuple[str, str], List[Any]] = {}
        for (vehicle_id, from_trip_id, to_trip_id), var in x.items():
            outgoing_by_node.setdefault((vehicle_id, from_trip_id), []).append(var)
            incoming_by_node.setdefault((vehicle_id, to_trip_id), []).append(var)
            if (vehicle_id, from_trip_id) in y:
                model.addConstr(var <= y[(vehicle_id, from_trip_id)])
            if (vehicle_id, to_trip_id) in y:
                model.addConstr(var <= y[(vehicle_id, to_trip_id)])

        # Arc-flow constraints: one predecessor/successor with explicit start/end indicators.
        for vehicle in problem.vehicles:
            vehicle_terms_start: List[Any] = []
            vehicle_terms_end: List[Any] = []
            for trip in problem.trips:
                key = (vehicle.vehicle_id, trip.trip_id)
                if key not in y:
                    continue
                incoming = gp.quicksum(incoming_by_node.get(key, []))
                outgoing = gp.quicksum(outgoing_by_node.get(key, []))
                model.addConstr(incoming + start_arc[key] == y[key])
                model.addConstr(outgoing + end_arc[key] == y[key])
                vehicle_terms_start.append(start_arc[key])
                vehicle_terms_end.append(end_arc[key])
            model.addConstr(gp.quicksum(vehicle_terms_start) <= 1)
            model.addConstr(gp.quicksum(vehicle_terms_end) <= 1)

        bev_ids = [
            vehicle.vehicle_id
            for vehicle in problem.vehicles
            if vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}
        ]
        slot_indices = sorted({slot.slot_index for slot in problem.price_slots})
        timestep_h = max(problem.scenario.timestep_min, 1) / 60.0

        c_var: Dict[Tuple[str, int], Any] = {}
        d_var: Dict[Tuple[str, int], Any] = {}
        s_var: Dict[Tuple[str, int], Any] = {}
        g_var: Dict[int, Any] = {}
        pv_ch_var: Dict[int, Any] = {}
        p_avg_var: Dict[int, Any] = {}
        w_on_var = None
        w_off_var = None

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

                # C11: terminal SOC lower bound for used vehicles.
                last_slot = slot_indices[-1]
                model.addConstr(s_var[(vehicle.vehicle_id, last_slot)] >= soc_min * used_vehicle[vehicle.vehicle_id])

                for pos in range(len(slot_indices) - 1):
                    slot_idx = slot_indices[pos]
                    next_slot_idx = slot_indices[pos + 1]
                    trip_energy_expr = gp.quicksum(
                        trip.energy_kwh * y[(vehicle.vehicle_id, trip.trip_id)]
                        for trip in problem.trips
                        if (vehicle.vehicle_id, trip.trip_id) in y
                        and self._slot_index(problem, trip.departure_min) == slot_idx
                    )
                    # C8: deadhead energy consumption linked with selected connection arcs.
                    deadhead_energy_expr = gp.quicksum(
                        self._deadhead_energy_kwh(problem, vehicle.vehicle_type, from_trip_id, to_trip_id)
                        * x[(vehicle.vehicle_id, from_trip_id, to_trip_id)]
                        for from_trip_id, to_trip_id in [
                            (f_trip, t_trip)
                            for v_id, f_trip, t_trip in arc_pairs
                            if v_id == vehicle.vehicle_id
                        ]
                        if self._slot_index(problem, trip_by_id[to_trip_id].departure_min) == slot_idx
                    )
                    model.addConstr(
                        s_var[(vehicle.vehicle_id, next_slot_idx)]
                        == s_var[(vehicle.vehicle_id, slot_idx)]
                        + 0.95 * c_var[(vehicle.vehicle_id, slot_idx)] * timestep_h
                        - d_var[(vehicle.vehicle_id, slot_idx)] * timestep_h / 0.95
                        - trip_energy_expr
                        - deadhead_energy_expr
                    )

                    # C12: no charging while vehicle is operating a trip in this slot.
                    running_expr = gp.quicksum(
                        y[(vehicle.vehicle_id, trip.trip_id)]
                        for trip in problem.trips
                        if (vehicle.vehicle_id, trip.trip_id) in y
                        and self._trip_active_in_slot(problem, trip.departure_min, trip.arrival_min, slot_idx)
                    )
                    model.addConstr(c_var[(vehicle.vehicle_id, slot_idx)] <= charge_max_kw * (1 - running_expr))

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

        # C15-C21: grid/PV balance, non-backflow, contract limit and demand charges.
        if slot_indices:
            for slot in problem.price_slots:
                slot_idx = slot.slot_index
                g_var[slot_idx] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"g[{slot_idx}]")
                pv_ch_var[slot_idx] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"pv_ch[{slot_idx}]")
                p_avg_var[slot_idx] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"p_avg[{slot_idx}]")

            w_on_var = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="w_on")
            w_off_var = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="w_off")

            pv_by_slot = {slot.slot_index: slot.pv_available_kw for slot in problem.pv_slots}
            contract_limit_kw = max((depot.import_limit_kw for depot in problem.depots), default=1.0e6)
            price_values = [slot.grid_buy_yen_per_kwh for slot in problem.price_slots]
            median_price = sorted(price_values)[len(price_values) // 2] if price_values else 0.0

            for slot in problem.price_slots:
                slot_idx = slot.slot_index
                charge_kwh_expr = gp.quicksum(
                    c_var[(vehicle_id, slot_idx)] * timestep_h
                    for vehicle_id in bev_ids
                    if (vehicle_id, slot_idx) in c_var
                )
                model.addConstr(g_var[slot_idx] + pv_ch_var[slot_idx] == charge_kwh_expr)  # C15
                model.addConstr(pv_ch_var[slot_idx] <= max(pv_by_slot.get(slot_idx, 0.0), 0.0) * timestep_h)  # C16
                model.addConstr(g_var[slot_idx] <= contract_limit_kw * timestep_h)  # C18

                # C19: period average demand (one slot period).
                model.addConstr(p_avg_var[slot_idx] == g_var[slot_idx] / timestep_h)

                # C20/C21: on/off peak maximum demand.
                if slot.grid_buy_yen_per_kwh >= median_price:
                    model.addConstr(w_on_var >= p_avg_var[slot_idx])
                else:
                    model.addConstr(w_off_var >= p_avg_var[slot_idx])

        unserved_penalty_weight = max(problem.objective_weights.unserved, 10000.0)

        objective = gp.LinExpr()
        # O2: strict TOU energy purchase cost.
        price_by_slot = {slot.slot_index: slot.grid_buy_yen_per_kwh for slot in problem.price_slots}
        for slot_idx, g in g_var.items():
            objective += price_by_slot.get(slot_idx, 0.0) * g

        # O1: ICE fuel cost (revenue + deadhead).
        diesel_price = max(problem.scenario.diesel_price_yen_per_l, 0.0)
        for (vehicle_id, trip_id), var in y.items():
            vehicle = next((v for v in problem.vehicles if v.vehicle_id == vehicle_id), None)
            if vehicle is None or vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}:
                continue
            trip = trip_by_id.get(trip_id)
            if trip is None:
                continue
            fuel_l = max(trip.fuel_l, 0.0)
            if fuel_l <= 0 and vehicle.fuel_consumption_l_per_km:
                fuel_l = max(trip.distance_km, 0.0) * vehicle.fuel_consumption_l_per_km
            objective += diesel_price * fuel_l * var

        for (vehicle_id, from_trip_id, to_trip_id), var in x.items():
            vehicle = next((v for v in problem.vehicles if v.vehicle_id == vehicle_id), None)
            if vehicle is None or vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}:
                continue
            fuel_rate = vehicle.fuel_consumption_l_per_km or 0.0
            if fuel_rate <= 0:
                continue
            deadhead_min = problem.dispatch_context.get_deadhead_min(
                trip_by_id[from_trip_id].destination,
                trip_by_id[to_trip_id].origin,
            )
            deadhead_km = (deadhead_min / 60.0) * 20.0
            objective += diesel_price * deadhead_km * fuel_rate * var

        # O3: demand charge cost.
        if w_on_var is not None and w_off_var is not None:
            objective += max(problem.scenario.demand_charge_on_peak_yen_per_kw, 0.0) * w_on_var
            objective += max(problem.scenario.demand_charge_off_peak_yen_per_kw, 0.0) * w_off_var

        for (vehicle_id, trip_id), var in y.items():
            _ = vehicle_id, trip_id, var
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

    def _trip_active_in_slot(
        self,
        problem: CanonicalOptimizationProblem,
        departure_min: int,
        arrival_min: int,
        slot_idx: int,
    ) -> bool:
        timestep_min = max(problem.scenario.timestep_min, 1)
        slot_start = self._slot_absolute_min(problem, slot_idx)
        slot_end = slot_start + timestep_min
        dep = departure_min
        arr = arrival_min
        if arr < dep:
            arr += 24 * 60
        if dep < slot_start - 24 * 60:
            dep += 24 * 60
            arr += 24 * 60
        return dep < slot_end and arr > slot_start

    def _slot_absolute_min(self, problem: CanonicalOptimizationProblem, slot_idx: int) -> int:
        timestep_min = max(problem.scenario.timestep_min, 1)
        if not problem.scenario.horizon_start:
            return slot_idx * timestep_min
        try:
            hh, mm = problem.scenario.horizon_start.split(":")
            start_min = int(hh) * 60 + int(mm)
        except ValueError:
            start_min = 0
        return start_min + slot_idx * timestep_min

    def _deadhead_energy_kwh(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle_type: str,
        from_trip_id: str,
        to_trip_id: str,
    ) -> float:
        from_trip = problem.trip_by_id().get(from_trip_id)
        to_trip = problem.trip_by_id().get(to_trip_id)
        if from_trip is None or to_trip is None:
            return 0.0
        deadhead_min = problem.dispatch_context.get_deadhead_min(
            from_trip.destination,
            to_trip.origin,
        )
        deadhead_km = (deadhead_min / 60.0) * 20.0
        vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle_type), None)
        if vt and vt.powertrain_type.upper() in {"BEV", "PHEV", "FCEV"}:
            drive_rate = max((from_trip.energy_kwh / max(from_trip.distance_km, 1e-6)), 0.0)
            return deadhead_km * drive_rate
        return 0.0

