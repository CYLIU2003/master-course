from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, Set, Tuple

from src.dispatch.models import DutyLeg, VehicleDuty
from src.gurobi_runtime import ensure_gurobi, is_gurobi_available
from src.objective_modes import normalize_objective_mode
from src.optimization.milp.model_builder import MILPModelBuilder

from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargingSlot,
    DepotEnergyAsset,
    OptimizationConfig,
    ProblemTrip,
    RefuelSlot,
    classify_peak_slots,
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
        if not is_gurobi_available():
            baseline = problem.baseline_plan or AssignmentPlan()
            return (
                MILPSolverOutcome(
                    solver_status="gurobi_unavailable_baseline",
                    used_backend="dispatch_baseline",
                    supports_exact_milp=False,
                ),
                baseline,
            )

        gp, GRB = ensure_gurobi()
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

        allow_partial_service = bool(problem.metadata.get("allow_partial_service", False))
        if not allow_partial_service:
            for trip in problem.trips:
                model.addConstr(unserved[trip.trip_id] == 0)

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

        max_start_fragments_per_vehicle = self._safe_positive_int(
            problem.metadata.get("max_start_fragments_per_vehicle"),
            default=1,
        )
        max_end_fragments_per_vehicle = self._safe_positive_int(
            problem.metadata.get("max_end_fragments_per_vehicle"),
            default=1,
        )

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
            model.addConstr(gp.quicksum(vehicle_terms_start) <= max_start_fragments_per_vehicle)
            model.addConstr(gp.quicksum(vehicle_terms_end) <= max_end_fragments_per_vehicle)

        # Fixed route-band mode: one vehicle can serve at most one route family (fallback: route_id).
        fixed_route_band_mode = bool(problem.metadata.get("fixed_route_band_mode", False))
        if fixed_route_band_mode:
            route_band_by_trip_id = {
                trip.trip_id: self._route_band_key(dispatch_trip_by_id.get(trip.trip_id), trip.route_id)
                for trip in problem.trips
            }
            route_bands = sorted({band for band in route_band_by_trip_id.values() if band})
            route_band_use: Dict[Tuple[str, str], Any] = {
                (vehicle.vehicle_id, band): model.addVar(vtype=GRB.BINARY)
                for vehicle in problem.vehicles
                for band in route_bands
            }
            for (vehicle_id, trip_id), var in y.items():
                band = route_band_by_trip_id.get(trip_id)
                if not band:
                    continue
                band_var = route_band_use.get((vehicle_id, band))
                if band_var is not None:
                    model.addConstr(var <= band_var)
            for vehicle in problem.vehicles:
                vehicle_band_vars = [
                    route_band_use[(vehicle.vehicle_id, band)]
                    for band in route_bands
                    if (vehicle.vehicle_id, band) in route_band_use
                ]
                if vehicle_band_vars:
                    model.addConstr(gp.quicksum(vehicle_band_vars) <= 1)
                    for band_var in vehicle_band_vars:
                        model.addConstr(band_var <= used_vehicle[vehicle.vehicle_id])

        # C5: Explicit time-overlap prohibition.
        # For each vehicle k and each overlapping trip pair (i, j) add y[k,i] + y[k,j] <= 1.
        trip_list = list(problem.trips)
        for veh in problem.vehicles:
            for a_idx in range(len(trip_list)):
                t_a = trip_list[a_idx]
                key_a = (veh.vehicle_id, t_a.trip_id)
                if key_a not in y:
                    continue
                for b_idx in range(a_idx + 1, len(trip_list)):
                    t_b = trip_list[b_idx]
                    key_b = (veh.vehicle_id, t_b.trip_id)
                    if key_b not in y:
                        continue
                    if self._trips_overlap(t_a, t_b):
                        model.addConstr(y[key_a] + y[key_b] <= 1)

        bev_ids = [
            vehicle.vehicle_id
            for vehicle in problem.vehicles
            if vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}
        ]
        electric_vehicle_ids = set(bev_ids)
        slot_indices = sorted({slot.slot_index for slot in problem.price_slots})
        timestep_h = max(problem.scenario.timestep_min, 1) / 60.0
        electric_trip_kwh_by_slot: Dict[int, List[Tuple[float, Tuple[str, str]]]] = {
            slot_idx: [] for slot_idx in slot_indices
        }
        electric_deadhead_kwh_by_slot: Dict[int, List[Tuple[float, Tuple[str, str, str]]]] = {
            slot_idx: [] for slot_idx in slot_indices
        }
        for vehicle in problem.vehicles:
            if vehicle.vehicle_id not in electric_vehicle_ids:
                continue
            for trip in problem.trips:
                key = (vehicle.vehicle_id, trip.trip_id)
                if key not in y:
                    continue
                trip_slot_indices = self._slot_indices_for_interval(
                    problem,
                    trip.departure_min,
                    trip.arrival_min,
                )
                if not trip_slot_indices:
                    continue
                energy_per_slot = max(trip.energy_kwh, 0.0) / len(trip_slot_indices)
                if energy_per_slot <= 0.0:
                    continue
                for slot_idx in trip_slot_indices:
                    electric_trip_kwh_by_slot.setdefault(slot_idx, []).append((energy_per_slot, key))
            for vehicle_id, from_trip_id, to_trip_id in arc_pairs:
                if vehicle_id != vehicle.vehicle_id:
                    continue
                deadhead_kwh = self._deadhead_energy_kwh(
                    problem,
                    vehicle.vehicle_type,
                    from_trip_id,
                    to_trip_id,
                )
                if deadhead_kwh <= 0.0:
                    continue
                slot_idx = self._slot_index(problem, trip_by_id[to_trip_id].departure_min)
                electric_deadhead_kwh_by_slot.setdefault(slot_idx, []).append(
                    (deadhead_kwh, (vehicle_id, from_trip_id, to_trip_id))
                )

        c_var: Dict[Tuple[str, int], Any] = {}
        d_var: Dict[Tuple[str, int], Any] = {}
        charge_on_var: Dict[Tuple[str, int], Any] = {}
        s_var: Dict[Tuple[str, int], Any] = {}
        fuel_l_var: Dict[Tuple[str, int], Any] = {}
        refuel_l_var: Dict[Tuple[str, int], Any] = {}
        g_var: Dict[int, Any] = {}
        pv_ch_var: Dict[int, Any] = {}
        p_avg_var: Dict[int, Any] = {}
        g2bus_var: Dict[Tuple[str, int], Any] = {}
        g2bess_var: Dict[Tuple[str, int], Any] = {}
        pv2bess_var: Dict[Tuple[str, int], Any] = {}
        bess2bus_var: Dict[Tuple[str, int], Any] = {}
        pv_curt_var: Dict[Tuple[str, int], Any] = {}
        bess_soc_var: Dict[Tuple[str, int], Any] = {}
        grid_import_var: Dict[Tuple[str, int], Any] = {}
        p_avg_depot_var: Dict[Tuple[str, int], Any] = {}
        w_on_depot_var: Dict[str, Any] = {}
        w_off_depot_var: Dict[str, Any] = {}
        bess_charge_mode_var: Dict[Tuple[str, int], Any] = {}
        bess_discharge_mode_var: Dict[Tuple[str, int], Any] = {}
        end_soc_excess_dev_var: Dict[str, Any] = {}
        w_on_var = None
        w_off_var = None

        if bev_ids and slot_indices:
            initial_soc_ratio_override = self._percent_to_ratio(problem.metadata.get("initial_soc_percent"))
            final_soc_floor_ratio_override = self._percent_to_ratio(problem.metadata.get("final_soc_floor_percent"))
            final_soc_target_ratio_override = self._percent_to_ratio(problem.metadata.get("final_soc_target_percent"))
            final_soc_target_tolerance_ratio_override = self._percent_to_ratio(
                problem.metadata.get("final_soc_target_tolerance_percent")
            )
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
                    charge_on_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(vtype=GRB.BINARY)
                    c_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(lb=0.0, ub=charge_max_kw, vtype=GRB.CONTINUOUS)
                    d_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(lb=0.0, ub=discharge_max_kw, vtype=GRB.CONTINUOUS)
                    s_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(lb=soc_min, ub=cap, vtype=GRB.CONTINUOUS)

                if initial_soc_ratio_override is not None:
                    initial_kwh = initial_soc_ratio_override * cap
                else:
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
                final_soc_floor_kwh = soc_min
                if final_soc_floor_ratio_override is not None:
                    final_soc_floor_kwh = max(final_soc_floor_kwh, final_soc_floor_ratio_override * cap)
                model.addConstr(
                    s_var[(vehicle.vehicle_id, last_slot)]
                    >= final_soc_floor_kwh * used_vehicle[vehicle.vehicle_id]
                )

                # End-of-day SOC target: soft objective to approach configured target by horizon end.
                if final_soc_target_ratio_override is not None:
                    target_kwh = min(max(final_soc_target_ratio_override * cap, soc_min), cap)
                    tolerance_ratio = 0.0
                    if final_soc_target_tolerance_ratio_override is not None:
                        tolerance_ratio = min(max(final_soc_target_tolerance_ratio_override, 0.0), 1.0)
                    tolerance_kwh = tolerance_ratio * cap
                    excess_dev = model.addVar(lb=0.0, ub=cap, vtype=GRB.CONTINUOUS)
                    end_soc_excess_dev_var[vehicle.vehicle_id] = excess_dev
                    model.addConstr(
                        excess_dev
                        >= s_var[(vehicle.vehicle_id, last_slot)]
                        - (target_kwh + tolerance_kwh)
                        - cap * (1 - used_vehicle[vehicle.vehicle_id])
                    )
                    model.addConstr(
                        excess_dev
                        >= (target_kwh - tolerance_kwh)
                        - s_var[(vehicle.vehicle_id, last_slot)]
                        - cap * (1 - used_vehicle[vehicle.vehicle_id])
                    )

                # C10 (departure readiness): each assigned BEV trip must start with sufficient SOC.
                for trip in problem.trips:
                    key = (vehicle.vehicle_id, trip.trip_id)
                    if key not in y:
                        continue
                    required_ratio = self._percent_to_ratio(trip.required_soc_departure_percent)
                    if required_ratio is None or required_ratio <= 0.0:
                        continue
                    depart_slot_idx = self._slot_index(problem, trip.departure_min)
                    if (vehicle.vehicle_id, depart_slot_idx) not in s_var:
                        continue
                    model.addConstr(
                        s_var[(vehicle.vehicle_id, depart_slot_idx)]
                        >= (required_ratio * cap) * y[key]
                    )

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
                    model.addConstr(charge_on_var[(vehicle.vehicle_id, slot_idx)] <= 1 - running_expr)
                    model.addConstr(
                        c_var[(vehicle.vehicle_id, slot_idx)]
                        <= charge_max_kw * charge_on_var[(vehicle.vehicle_id, slot_idx)]
                    )

            if problem.chargers:
                total_ports = sum(max(charger.simultaneous_ports, 1) for charger in problem.chargers)
                total_kw = sum(
                    charger.power_kw * max(charger.simultaneous_ports, 1)
                    for charger in problem.chargers
                )
                for slot_idx in slot_indices:
                    model.addConstr(
                        gp.quicksum(charge_on_var[(vehicle_id, slot_idx)] for vehicle_id in bev_ids)
                        <= total_ports
                    )
                    model.addConstr(
                        gp.quicksum(c_var[(vehicle_id, slot_idx)] for vehicle_id in bev_ids)
                        <= total_kw
                    )

        # ICE finite-fuel constraints: check before departure and update after operation.
        if slot_indices:
            initial_ice_fuel_ratio_override = self._percent_to_ratio(
                problem.metadata.get("initial_ice_fuel_percent")
            )
            min_ice_fuel_ratio_override = self._percent_to_ratio(
                problem.metadata.get("min_ice_fuel_percent")
            )
            max_ice_fuel_ratio_override = self._percent_to_ratio(
                problem.metadata.get("max_ice_fuel_percent")
            )
            default_ice_tank_capacity_l = self._safe_nonnegative_float(
                problem.metadata.get("default_ice_tank_capacity_l"),
                default=300.0,
            )
            refuel_duration_h = 5.0 / 60.0
            for vehicle in problem.vehicles:
                if vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}:
                    continue
                fuel_rate = max(float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0)
                if fuel_rate <= 0.0:
                    continue

                tank_cap_l = float(vehicle.fuel_tank_capacity_l or 0.0)
                if tank_cap_l <= 0.0:
                    tank_cap_l = default_ice_tank_capacity_l
                if tank_cap_l <= 0.0:
                    continue

                reserve_l = max(float(vehicle.fuel_reserve_l or 0.0), 0.0)
                if min_ice_fuel_ratio_override is not None:
                    reserve_l = max(reserve_l, min_ice_fuel_ratio_override * tank_cap_l)
                reserve_l = min(reserve_l, tank_cap_l)

                upper_buffer_l = tank_cap_l
                if max_ice_fuel_ratio_override is not None:
                    upper_buffer_l = min(tank_cap_l, max_ice_fuel_ratio_override * tank_cap_l)
                upper_buffer_l = max(upper_buffer_l, reserve_l)
                refuel_rate_l_per_h = 0.0
                if upper_buffer_l > reserve_l:
                    refuel_rate_l_per_h = (upper_buffer_l - reserve_l) / refuel_duration_h
                refuel_per_slot_l = refuel_rate_l_per_h * timestep_h

                for slot_idx in slot_indices:
                    fuel_l_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(
                        lb=reserve_l,
                        ub=tank_cap_l,
                        vtype=GRB.CONTINUOUS,
                    )
                    refuel_l_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(
                        lb=0.0,
                        ub=max(refuel_per_slot_l, 0.0),
                        vtype=GRB.CONTINUOUS,
                    )

                if initial_ice_fuel_ratio_override is not None:
                    initial_l = initial_ice_fuel_ratio_override * tank_cap_l
                else:
                    initial_l = float(vehicle.initial_fuel_l or tank_cap_l)
                initial_l = min(max(initial_l, reserve_l), tank_cap_l)

                first_slot = slot_indices[0]
                model.addConstr(fuel_l_var[(vehicle.vehicle_id, first_slot)] == initial_l)

                for trip in problem.trips:
                    key = (vehicle.vehicle_id, trip.trip_id)
                    if key not in y:
                        continue
                    depart_slot_idx = self._slot_index(problem, trip.departure_min)
                    fuel_required_l = self._trip_fuel_l(problem, vehicle, trip.trip_id)
                    if fuel_required_l <= 0.0:
                        continue
                    if (vehicle.vehicle_id, depart_slot_idx) not in fuel_l_var:
                        continue
                    model.addConstr(
                        fuel_l_var[(vehicle.vehicle_id, depart_slot_idx)]
                        >= fuel_required_l * y[key]
                    )

                for slot_idx in slot_indices:
                    running_expr = gp.quicksum(
                        y[(vehicle.vehicle_id, trip.trip_id)]
                        for trip in problem.trips
                        if (vehicle.vehicle_id, trip.trip_id) in y
                        and self._trip_active_in_slot(
                            problem,
                            trip.departure_min,
                            trip.arrival_min,
                            slot_idx,
                        )
                    )
                    model.addConstr(
                        refuel_l_var[(vehicle.vehicle_id, slot_idx)]
                        <= max(refuel_per_slot_l, 0.0) * (1 - running_expr)
                    )

                vehicle_arcs = [
                    (f_trip, t_trip)
                    for v_id, f_trip, t_trip in arc_pairs
                    if v_id == vehicle.vehicle_id
                ]
                for pos in range(len(slot_indices) - 1):
                    slot_idx = slot_indices[pos]
                    next_slot_idx = slot_indices[pos + 1]
                    trip_fuel_expr = gp.quicksum(
                        self._trip_fuel_l(problem, vehicle, trip.trip_id)
                        * y[(vehicle.vehicle_id, trip.trip_id)]
                        for trip in problem.trips
                        if (vehicle.vehicle_id, trip.trip_id) in y
                        and self._slot_index(problem, trip.departure_min) == slot_idx
                    )
                    deadhead_fuel_expr = gp.quicksum(
                        self._deadhead_fuel_l(problem, vehicle, from_trip_id, to_trip_id)
                        * x[(vehicle.vehicle_id, from_trip_id, to_trip_id)]
                        for from_trip_id, to_trip_id in vehicle_arcs
                        if self._slot_index(problem, trip_by_id[to_trip_id].departure_min) == slot_idx
                    )
                    model.addConstr(
                        fuel_l_var[(vehicle.vehicle_id, next_slot_idx)]
                        == fuel_l_var[(vehicle.vehicle_id, slot_idx)]
                        - trip_fuel_expr
                        - deadhead_fuel_expr
                        + refuel_l_var[(vehicle.vehicle_id, slot_idx)]
                    )

        # C15-C21(new): depot-level PV->BESS->Bus / Grid->Bus(+BESS) balance, demand and contract limits.
        if slot_indices:
            on_peak_slots, off_peak_slots = self._classify_peak_slots(problem)
            price_by_slot = {slot.slot_index: slot.grid_buy_yen_per_kwh for slot in problem.price_slots}
            vehicle_by_id = {v.vehicle_id: v for v in problem.vehicles}
            bev_ids_by_depot: Dict[str, List[str]] = {}
            for vehicle_id in bev_ids:
                vehicle = vehicle_by_id.get(vehicle_id)
                depot_key = str(getattr(vehicle, "home_depot_id", "") or "depot_default")
                bev_ids_by_depot.setdefault(depot_key, []).append(vehicle_id)

            depot_by_id = {d.depot_id: d for d in problem.depots}
            depot_energy_assets: Dict[str, DepotEnergyAsset] = {
                depot_id: asset for depot_id, asset in (problem.depot_energy_assets or {}).items()
            }
            if not depot_energy_assets:
                slot_count = len(slot_indices)
                pv_by_slot_kw = {slot.slot_index: max(float(slot.pv_available_kw or 0.0), 0.0) for slot in problem.pv_slots}
                pv_series = tuple(pv_by_slot_kw.get(slot_idx, 0.0) * timestep_h for slot_idx in slot_indices)
                default_depot = next(iter(depot_by_id.keys()), "depot_default")
                depot_energy_assets[default_depot] = DepotEnergyAsset(
                    depot_id=default_depot,
                    pv_enabled=bool(problem.pv_slots),
                    pv_generation_kwh_by_slot=pv_series if slot_count > 0 else (),
                    bess_enabled=False,
                )

            for depot_id, asset in depot_energy_assets.items():
                w_on_depot_var[depot_id] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                w_off_depot_var[depot_id] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)

                contract_limit_kw = float(
                    getattr(depot_by_id.get(depot_id), "import_limit_kw", 0.0) or 0.0
                )
                if contract_limit_kw <= 0.0:
                    contract_limit_kw = 1.0e6

                for slot_idx in slot_indices:
                    key = (depot_id, slot_idx)
                    g2bus_var[key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                    g2bess_var[key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                    pv2bess_var[key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                    bess2bus_var[key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                    pv_curt_var[key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                    grid_import_var[key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                    p_avg_depot_var[key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                    if asset.bess_enabled:
                        soc_lb = max(float(asset.bess_soc_min_kwh or 0.0), 0.0)
                        soc_ub = max(float(asset.bess_soc_max_kwh or 0.0), soc_lb)
                        bess_soc_var[key] = model.addVar(lb=soc_lb, ub=soc_ub, vtype=GRB.CONTINUOUS)

                    charge_kwh_expr = gp.quicksum(
                        c_var[(vehicle_id, slot_idx)] * timestep_h
                        for vehicle_id in bev_ids_by_depot.get(depot_id, [])
                        if (vehicle_id, slot_idx) in c_var
                    )
                    model.addConstr(bess2bus_var[key] + g2bus_var[key] == charge_kwh_expr)

                    pv_gen_kwh = 0.0
                    if asset.pv_enabled and asset.pv_generation_kwh_by_slot:
                        pos = slot_indices.index(slot_idx)
                        if pos < len(asset.pv_generation_kwh_by_slot):
                            pv_gen_kwh = max(float(asset.pv_generation_kwh_by_slot[pos] or 0.0), 0.0)
                    model.addConstr(pv2bess_var[key] + pv_curt_var[key] == pv_gen_kwh)

                    model.addConstr(grid_import_var[key] == g2bus_var[key] + g2bess_var[key])
                    model.addConstr(grid_import_var[key] <= contract_limit_kw * timestep_h)
                    model.addConstr(p_avg_depot_var[key] == grid_import_var[key] / timestep_h)

                    if slot_idx in on_peak_slots:
                        model.addConstr(w_on_depot_var[depot_id] >= p_avg_depot_var[key])
                    if slot_idx in off_peak_slots:
                        model.addConstr(w_off_depot_var[depot_id] >= p_avg_depot_var[key])

                    if not asset.allow_grid_to_bess:
                        model.addConstr(g2bess_var[key] == 0.0)
                    else:
                        threshold = max(float(asset.grid_to_bess_price_threshold_yen_per_kwh or 0.0), 0.0)
                        allowed_slots = set(int(v) for v in (asset.grid_to_bess_allowed_slot_indices or ()))
                        if allowed_slots and slot_idx not in allowed_slots:
                            model.addConstr(g2bess_var[key] == 0.0)
                        if threshold > 0.0 and float(price_by_slot.get(slot_idx, 0.0) or 0.0) > threshold:
                            model.addConstr(g2bess_var[key] == 0.0)

                    if not asset.bess_enabled:
                        model.addConstr(pv2bess_var[key] == 0.0)
                        model.addConstr(g2bess_var[key] == 0.0)
                        model.addConstr(bess2bus_var[key] == 0.0)

                if asset.bess_enabled and slot_indices:
                    eta_ch = max(float(asset.bess_charge_efficiency or 0.95), 1.0e-6)
                    eta_dis = max(float(asset.bess_discharge_efficiency or 0.95), 1.0e-6)
                    power_limit_kwh = max(float(asset.bess_power_kw or 0.0), 0.0) * timestep_h
                    first_slot = slot_indices[0]
                    model.addConstr(bess_soc_var[(depot_id, first_slot)] == float(asset.bess_initial_soc_kwh or 0.0))
                    terminal_soc_floor = max(
                        float(asset.bess_terminal_soc_min_kwh or 0.0),
                        float(asset.bess_soc_min_kwh or 0.0),
                    )
                    for slot_idx in slot_indices:
                        key = (depot_id, slot_idx)
                        bess_charge_mode_var[key] = model.addVar(vtype=GRB.BINARY)
                        bess_discharge_mode_var[key] = model.addVar(vtype=GRB.BINARY)
                        model.addConstr(
                            pv2bess_var[key] + g2bess_var[key]
                            <= power_limit_kwh * bess_charge_mode_var[key]
                        )
                        model.addConstr(
                            bess2bus_var[key]
                            <= power_limit_kwh * bess_discharge_mode_var[key]
                        )
                        model.addConstr(
                            bess_charge_mode_var[key] + bess_discharge_mode_var[key] <= 1
                        )
                    for idx in range(len(slot_indices) - 1):
                        slot_idx = slot_indices[idx]
                        next_slot = slot_indices[idx + 1]
                        cur_key = (depot_id, slot_idx)
                        nxt_key = (depot_id, next_slot)
                        model.addConstr(
                            bess_soc_var[nxt_key]
                            == bess_soc_var[cur_key]
                            + eta_ch * (pv2bess_var[cur_key] + g2bess_var[cur_key])
                            - (bess2bus_var[cur_key] / eta_dis)
                        )
                    last_key = (depot_id, slot_indices[-1])
                    model.addConstr(
                        bess_soc_var[last_key]
                        + eta_ch * (pv2bess_var[last_key] + g2bess_var[last_key])
                        - (bess2bus_var[last_key] / eta_dis)
                        >= terminal_soc_floor
                    )

            if w_on_depot_var:
                w_on_var = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                w_off_var = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                for depot_id in w_on_depot_var:
                    model.addConstr(w_on_var >= w_on_depot_var[depot_id])
                    model.addConstr(w_off_var >= w_off_depot_var[depot_id])

        unserved_penalty_weight = max(problem.objective_weights.unserved, 10000.0)
        objective_mode = normalize_objective_mode(problem.scenario.objective_mode)
        energy_weight = max(problem.objective_weights.energy, 0.0)
        demand_weight = max(problem.objective_weights.demand, 0.0)
        vehicle_weight = max(problem.objective_weights.vehicle, 0.0)

        objective = gp.LinExpr()
        # O2: electricity cost based on actual charging source flows.
        price_by_slot = {slot.slot_index: slot.grid_buy_yen_per_kwh for slot in problem.price_slots}
        curtail_penalty = self._safe_nonnegative_float(
            problem.metadata.get("pv_curtail_penalty_yen_per_kwh"),
            default=0.0,
        )
        if g2bus_var or g2bess_var or bess2bus_var:
            for (depot_id, slot_idx), var in g2bus_var.items():
                price = max(float(price_by_slot.get(slot_idx, 0.0) or 0.0), 0.0)
                objective += energy_weight * price * var
            for (depot_id, slot_idx), var in g2bess_var.items():
                price = max(float(price_by_slot.get(slot_idx, 0.0) or 0.0), 0.0)
                objective += energy_weight * price * var
            for (depot_id, slot_idx), var in bess2bus_var.items():
                asset = (problem.depot_energy_assets or {}).get(depot_id)
                bess_marginal = max(float(getattr(asset, "bess_cycle_cost_yen_per_kwh", 0.0) or 0.0), 0.0)
                objective += energy_weight * bess_marginal * var
            if curtail_penalty > 0.0:
                for var in pv_curt_var.values():
                    objective += energy_weight * curtail_penalty * var
        else:
            # Backward-compatible fallback for plans without charging-source variables.
            for slot_idx in slot_indices:
                price = price_by_slot.get(slot_idx, 0.0)
                if price <= 0.0:
                    continue
                for coeff, key in electric_trip_kwh_by_slot.get(slot_idx, []):
                    objective += energy_weight * price * coeff * y[key]
                for coeff, key in electric_deadhead_kwh_by_slot.get(slot_idx, []):
                    objective += energy_weight * price * coeff * x[key]

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
            objective += energy_weight * diesel_price * fuel_l * var

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
            deadhead_km = self._deadhead_distance_km(problem, deadhead_min)
            objective += energy_weight * diesel_price * deadhead_km * fuel_rate * var

        # O3: demand charge cost.
        if w_on_var is not None and w_off_var is not None:
            objective += demand_weight * max(problem.scenario.demand_charge_on_peak_yen_per_kw, 0.0) * w_on_var
            objective += demand_weight * max(problem.scenario.demand_charge_off_peak_yen_per_kw, 0.0) * w_off_var

        for vehicle in problem.vehicles:
            objective += vehicle_weight * vehicle.fixed_use_cost_jpy * used_vehicle[vehicle.vehicle_id]

        # CO₂ objective/cost: in CO2 mode, co2_price_per_kg is treated as a
        # positive scaling factor (defaulted to 1.0 upstream when omitted).
        co2_price = max(problem.scenario.co2_price_per_kg, 0.0)
        if objective_mode == "co2" and co2_price <= 0.0:
            co2_price = 1.0
        ice_co2_kg_per_l = max(problem.scenario.ice_co2_kg_per_l, 0.0)
        if co2_price > 0:
            # ICE CO₂ from trip fuel consumption.
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
                objective += co2_price * ice_co2_kg_per_l * fuel_l * var
            # ICE CO₂ from deadhead fuel consumption.
            for (vehicle_id, from_trip_id, to_trip_id), var in x.items():
                vehicle = next((v for v in problem.vehicles if v.vehicle_id == vehicle_id), None)
                if vehicle is None or vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}:
                    continue
                fuel_rate = vehicle.fuel_consumption_l_per_km or 0.0
                if fuel_rate <= 0:
                    continue
                dh_min = problem.dispatch_context.get_deadhead_min(
                    trip_by_id[from_trip_id].destination,
                    trip_by_id[to_trip_id].origin,
                )
                dh_km = self._deadhead_distance_km(problem, dh_min)
                objective += co2_price * ice_co2_kg_per_l * dh_km * fuel_rate * var
            # BEV electricity CO₂ (grid-sourced only, based on actual depot flows when available).
            co2_by_slot = {slot.slot_index: slot.co2_factor for slot in problem.price_slots}
            if g2bus_var or g2bess_var:
                for (depot_id, slot_idx), var in g2bus_var.items():
                    co2_factor = max(float(co2_by_slot.get(slot_idx, 0.0) or 0.0), 0.0)
                    if co2_factor > 0.0:
                        objective += co2_price * co2_factor * var
                for (depot_id, slot_idx), var in g2bess_var.items():
                    co2_factor = max(float(co2_by_slot.get(slot_idx, 0.0) or 0.0), 0.0)
                    if co2_factor > 0.0:
                        objective += co2_price * co2_factor * var
            else:
                for slot_idx in slot_indices:
                    co2_factor = co2_by_slot.get(slot_idx, 0.0)
                    if co2_factor > 0:
                        for coeff, key in electric_trip_kwh_by_slot.get(slot_idx, []):
                            objective += co2_price * co2_factor * coeff * y[key]
                        for coeff, key in electric_deadhead_kwh_by_slot.get(slot_idx, []):
                            objective += co2_price * co2_factor * coeff * x[key]

        # Battery degradation cost: added when weights.degradation > 0.
        # degradation_cost ≈ (charged_kwh / capacity_kwh) * unit_cost_per_cycle
        degradation_weight = problem.objective_weights.degradation
        if degradation_weight > 0:
            unit_cost_per_cycle = 50.0
            for vehicle in problem.vehicles:
                if vehicle.vehicle_id not in bev_ids:
                    continue
                cap = max(vehicle.battery_capacity_kwh or 300.0, 1.0)
                for slot_idx in slot_indices:
                    if (vehicle.vehicle_id, slot_idx) not in c_var:
                        continue
                    # charged_kwh = c_var * timestep_h; cycles = charged_kwh / cap
                    coeff = degradation_weight * unit_cost_per_cycle * timestep_h / cap
                    objective += coeff * c_var[(vehicle.vehicle_id, slot_idx)]

        # End-of-day SOC target deviation penalty (soft).
        if end_soc_excess_dev_var:
            target_penalty_per_kwh = self._safe_nonnegative_float(
                problem.metadata.get("final_soc_target_penalty_per_kwh"),
                default=50.0,
            )
            for dev in end_soc_excess_dev_var.values():
                objective += target_penalty_per_kwh * dev

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
        refuel_slots: List[RefuelSlot] = []
        charging_slots: List[ChargingSlot] = []
        depot_coordinates_by_id: Dict[str, Dict[str, float]] = {
            str(k): dict(v)
            for k, v in (problem.metadata.get("depot_coordinates_by_id") or {}).items()
            if isinstance(v, dict)
        }
        fallback_depot_coords = {
            str(depot.depot_id): {
                "lat": float(depot.latitude) if getattr(depot, "latitude", None) is not None else None,
                "lon": float(depot.longitude) if getattr(depot, "longitude", None) is not None else None,
            }
            for depot in problem.depots
        }

        def _depot_latlon(depot_id: str) -> Tuple[Any, Any]:
            point = depot_coordinates_by_id.get(depot_id) or fallback_depot_coords.get(depot_id) or {}
            return point.get("lat"), point.get("lon")

        def _var_val(var: Any) -> float:
            try:
                return float(var.X)
            except Exception:
                return 0.0

        grid_to_bus_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        bess_to_bus_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        pv_to_bess_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        grid_to_bess_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        pv_curtail_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        bess_soc_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        for (depot_id, slot_idx), var in g2bus_var.items():
            grid_to_bus_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = max(_var_val(var), 0.0)
        for (depot_id, slot_idx), var in bess2bus_var.items():
            bess_to_bus_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = max(_var_val(var), 0.0)
        for (depot_id, slot_idx), var in pv2bess_var.items():
            pv_to_bess_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = max(_var_val(var), 0.0)
        for (depot_id, slot_idx), var in g2bess_var.items():
            grid_to_bess_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = max(_var_val(var), 0.0)
        for (depot_id, slot_idx), var in pv_curt_var.items():
            pv_curtail_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = max(_var_val(var), 0.0)
        for (depot_id, slot_idx), var in bess_soc_var.items():
            bess_soc_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = max(_var_val(var), 0.0)

        if c_var and bev_ids:
            vehicle_by_id = {v.vehicle_id: v for v in problem.vehicles}
            for slot_idx in slot_indices:
                demand_by_depot_kwh: Dict[str, float] = {}
                demand_by_vehicle_kw: Dict[Tuple[str, str], float] = {}
                for vehicle_id in bev_ids:
                    var = c_var.get((vehicle_id, slot_idx))
                    if var is None:
                        continue
                    vehicle_kw = max(_var_val(var), 0.0)
                    if vehicle_kw <= 0.0:
                        continue
                    vehicle = vehicle_by_id.get(vehicle_id)
                    depot_id = str(getattr(vehicle, "home_depot_id", "") or "depot_default")
                    demand_by_depot_kwh[depot_id] = demand_by_depot_kwh.get(depot_id, 0.0) + vehicle_kw * timestep_h
                    demand_by_vehicle_kw[(vehicle_id, depot_id)] = vehicle_kw

                for (vehicle_id, depot_id), vehicle_kw in demand_by_vehicle_kw.items():
                    demand_kwh = demand_by_depot_kwh.get(depot_id, 0.0)
                    if demand_kwh <= 0.0:
                        continue
                    bess_kwh = float(bess_to_bus_kwh_by_depot_slot.get(depot_id, {}).get(slot_idx, 0.0) or 0.0)
                    grid_kwh = float(grid_to_bus_kwh_by_depot_slot.get(depot_id, {}).get(slot_idx, 0.0) or 0.0)
                    bess_ratio = min(max(bess_kwh / demand_kwh, 0.0), 1.0)
                    grid_ratio = min(max(grid_kwh / demand_kwh, 0.0), 1.0)
                    if bess_ratio > 0.0:
                        lat, lon = _depot_latlon(depot_id)
                        charging_slots.append(
                            ChargingSlot(
                                vehicle_id=vehicle_id,
                                slot_index=slot_idx,
                                charger_id=f"bess:{depot_id}",
                                charge_kw=vehicle_kw * bess_ratio,
                                discharge_kw=0.0,
                                charging_depot_id=depot_id,
                                charging_latitude=lat,
                                charging_longitude=lon,
                            )
                        )
                    if grid_ratio > 0.0:
                        lat, lon = _depot_latlon(depot_id)
                        charging_slots.append(
                            ChargingSlot(
                                vehicle_id=vehicle_id,
                                slot_index=slot_idx,
                                charger_id=f"grid:{depot_id}",
                                charge_kw=vehicle_kw * grid_ratio,
                                discharge_kw=0.0,
                                charging_depot_id=depot_id,
                                charging_latitude=lat,
                                charging_longitude=lon,
                            )
                        )

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

        for vehicle in problem.vehicles:
            if vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}:
                continue
            for slot_idx in slot_indices:
                key = (vehicle.vehicle_id, slot_idx)
                refuel_var = refuel_l_var.get(key)
                if refuel_var is None:
                    continue
                try:
                    refuel_l = float(refuel_var.X)
                except Exception:
                    continue
                if refuel_l <= 1.0e-6:
                    continue
                refuel_slots.append(
                    RefuelSlot(
                        vehicle_id=vehicle.vehicle_id,
                        slot_index=slot_idx,
                        refuel_liters=round(refuel_l, 4),
                        location_id=str(vehicle.home_depot_id or ""),
                    )
                )

        plan = AssignmentPlan(
            duties=tuple(duties),
            charging_slots=tuple(sorted(charging_slots, key=lambda item: (item.vehicle_id, item.slot_index, str(item.charger_id or "")))),
            refuel_slots=tuple(sorted(refuel_slots, key=lambda item: (item.vehicle_id, item.slot_index))),
            grid_to_bus_kwh_by_depot_slot=grid_to_bus_kwh_by_depot_slot,
            bess_to_bus_kwh_by_depot_slot=bess_to_bus_kwh_by_depot_slot,
            pv_to_bess_kwh_by_depot_slot=pv_to_bess_kwh_by_depot_slot,
            grid_to_bess_kwh_by_depot_slot=grid_to_bess_kwh_by_depot_slot,
            pv_curtail_kwh_by_depot_slot=pv_curtail_kwh_by_depot_slot,
            bess_soc_kwh_by_depot_slot=bess_soc_kwh_by_depot_slot,
            served_trip_ids=tuple(sorted(served_set)),
            unserved_trip_ids=tuple(unserved_trip_ids),
            metadata={
                "source": "milp_gurobi",
                "status": solver_status,
                "objective_value": float(model.ObjVal),
                "horizon_start": str(problem.scenario.horizon_start or "00:00"),
                "timestep_min": int(problem.scenario.timestep_min),
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

    def _slot_indices_for_interval(
        self,
        problem: CanonicalOptimizationProblem,
        departure_min: int,
        arrival_min: int,
    ) -> Tuple[int, ...]:
        start_idx = self._slot_index(problem, departure_min)
        adjusted_arrival = max(arrival_min - 1, departure_min)
        end_idx = self._slot_index(problem, adjusted_arrival)
        if end_idx < start_idx:
            end_idx = start_idx
        return tuple(range(start_idx, end_idx + 1))

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
        deadhead_km = self._deadhead_distance_km(problem, deadhead_min)
        vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle_type), None)
        if vt and vt.powertrain_type.upper() in {"BEV", "PHEV", "FCEV"}:
            drive_rate = max((from_trip.energy_kwh / max(from_trip.distance_km, 1e-6)), 0.0)
            return deadhead_km * drive_rate
        return 0.0

    def _trip_fuel_l(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        trip_id: str,
    ) -> float:
        trip = problem.trip_by_id().get(trip_id)
        if trip is None:
            return 0.0
        fuel_l = max(float(trip.fuel_l or 0.0), 0.0)
        if fuel_l > 0.0:
            return fuel_l
        fuel_rate = max(float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0)
        return max(float(trip.distance_km or 0.0), 0.0) * fuel_rate

    def _deadhead_fuel_l(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        from_trip_id: str,
        to_trip_id: str,
    ) -> float:
        fuel_rate = max(float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0)
        if fuel_rate <= 0.0:
            return 0.0
        from_trip = problem.trip_by_id().get(from_trip_id)
        to_trip = problem.trip_by_id().get(to_trip_id)
        if from_trip is None or to_trip is None:
            return 0.0
        deadhead_min = problem.dispatch_context.get_deadhead_min(
            from_trip.destination,
            to_trip.origin,
        )
        deadhead_km = self._deadhead_distance_km(problem, deadhead_min)
        return max(deadhead_km, 0.0) * fuel_rate

    def _deadhead_distance_km(self, problem: CanonicalOptimizationProblem, deadhead_min: int) -> float:
        speed_kmh = self._safe_nonnegative_float(
            problem.metadata.get("deadhead_speed_kmh"),
            default=18.0,
        )
        return max(float(deadhead_min or 0), 0.0) * speed_kmh / 60.0

    def _classify_peak_slots(self, problem: CanonicalOptimizationProblem) -> Tuple[Set[int], Set[int]]:
        return classify_peak_slots(problem.price_slots)

    def _trips_overlap(self, t_a: ProblemTrip, t_b: ProblemTrip) -> bool:
        """Return True if trips t_a and t_b have overlapping operating time intervals."""
        dep_a, arr_a = t_a.departure_min, t_a.arrival_min
        dep_b, arr_b = t_b.departure_min, t_b.arrival_min
        # Wrap midnight crossings within the same 24-hour window.
        if arr_a <= dep_a:
            arr_a += 24 * 60
        if arr_b <= dep_b:
            arr_b += 24 * 60
        return dep_a < arr_b and dep_b < arr_a

    def _safe_positive_int(self, value: Any, *, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed >= 1 else default

    def _safe_nonnegative_float(self, value: Any, *, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed >= 0.0 else default

    def _route_band_key(self, dispatch_trip: Any, fallback_route_id: str) -> str:
        family_code = str(getattr(dispatch_trip, "route_family_code", "") or "").strip()
        if family_code:
            return family_code
        return str(fallback_route_id or "").strip()

    def _percent_to_ratio(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed < 0.0:
            return None
        if parsed > 1.0:
            parsed = parsed / 100.0
        return min(parsed, 1.0)

