from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Protocol, Set, Tuple

from src.dispatch.feasibility import evaluate_startup_feasibility
from src.dispatch.models import DutyLeg, VehicleDuty
from src.dispatch.route_band import fragment_transition_diagnostic
from src.gurobi_runtime import ensure_gurobi, is_gurobi_available
from src.objective_modes import normalize_objective_mode
from src.optimization.common.cost_components import normalize_cost_component_flags
from src.optimization.milp.model_builder import MILPModelBuilder
from src.route_code_utils import extract_route_series_from_candidates

from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargingSlot,
    DepotEnergyAsset,
    OptimizationConfig,
    ProblemTrip,
    RefuelSlot,
    classify_peak_slots,
    normalize_service_coverage_mode,
    normalize_required_soc_departure_ratio,
)


_DRIVER_PREP_TIME_MIN = 30.0
_DRIVER_WAGE_JPY_PER_H = 2000.0
_DRIVER_REGULAR_HOURS_PER_DAY = 8.0
_DRIVER_OVERTIME_FACTOR = 1.25


@dataclass(frozen=True)
class MILPSolverOutcome:
    solver_status: str
    used_backend: str
    supports_exact_milp: bool
    has_feasible_incumbent: bool = False
    incumbent_count: int = 0
    warm_start_applied: bool = False
    warm_start_source: str = ""
    best_bound: Optional[float] = None
    final_gap: Optional[float] = None
    nodes_explored: Optional[int] = None
    runtime_sec: float = 0.0
    first_feasible_sec: Optional[float] = None
    presolve_reduction_summary: Dict[str, Any] = field(default_factory=dict)
    iis_generated: bool = False
    fallback_reason: str = ""


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
        service_coverage_mode = normalize_service_coverage_mode(
            getattr(problem.scenario, "service_coverage_mode", None)
            or problem.metadata.get("service_coverage_mode", "strict")
        )
        has_feasible_incumbent = bool(plan.served_trip_ids) and not (
            service_coverage_mode == "strict" and plan.unserved_trip_ids
        )
        if not has_feasible_incumbent:
            plan = AssignmentPlan(
                duties=(),
                charging_slots=(),
                served_trip_ids=(),
                unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips)),
                metadata={"source": "dispatch_baseline", "status": "strict_infeasible"},
            )
        return (
            MILPSolverOutcome(
                solver_status="baseline_feasible" if has_feasible_incumbent else "baseline_infeasible_strict",
                used_backend=self.backend_name,
                supports_exact_milp=False,
                has_feasible_incumbent=has_feasible_incumbent,
                incumbent_count=1 if has_feasible_incumbent else 0,
                warm_start_source=str((plan.metadata or {}).get("source") or ""),
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
            service_coverage_mode = normalize_service_coverage_mode(
                getattr(problem.scenario, "service_coverage_mode", None)
                or problem.metadata.get("service_coverage_mode", "strict")
            )
            has_feasible_incumbent = bool(baseline.served_trip_ids) and not (
                service_coverage_mode == "strict" and baseline.unserved_trip_ids
            )
            if not has_feasible_incumbent:
                baseline = AssignmentPlan(
                    duties=(),
                    charging_slots=(),
                    served_trip_ids=(),
                    unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips)),
                    metadata={"source": "dispatch_baseline", "status": "strict_infeasible"},
                )
            return (
                MILPSolverOutcome(
                    solver_status="gurobi_unavailable_baseline"
                    if has_feasible_incumbent
                    else "gurobi_unavailable_strict_infeasible",
                    used_backend="dispatch_baseline",
                    supports_exact_milp=False,
                    has_feasible_incumbent=has_feasible_incumbent,
                    incumbent_count=1 if has_feasible_incumbent else 0,
                    warm_start_source=str((baseline.metadata or {}).get("source") or ""),
                    fallback_reason="gurobi_unavailable_baseline" if has_feasible_incumbent else "",
                ),
                baseline,
            )

        gp, GRB = ensure_gurobi()
        model = gp.Model("optimization_milp_adapter")
        
        # Enable diagnostic logging if requested via environment variable
        import os
        enable_milp_diagnostics = bool(os.environ.get("MILP_ENABLE_DIAGNOSTICS", ""))
        diagnostic_output_dir = os.environ.get("MILP_DIAGNOSTIC_DIR", "output/milp_diagnostics")
        
        if enable_milp_diagnostics:
            from pathlib import Path
            Path(diagnostic_output_dir).mkdir(parents=True, exist_ok=True)
            model.Params.OutputFlag = 1
            log_file = os.path.join(diagnostic_output_dir, f"gurobi_{int(time.time())}.log")
            model.Params.LogFile = log_file
            print(f"[MILP Diagnostics] Gurobi log will be written to: {log_file}")
        else:
            model.Params.OutputFlag = 0
            
        model.Params.TimeLimit = max(1, int(config.time_limit_sec))
        model.Params.MIPGap = max(float(config.mip_gap), 0.0)
        model.Params.Seed = int(config.random_seed)
        
        # Feasibility-focused Gurobi parameters
        model.Params.MIPFocus = 1  # Focus on finding feasible solutions
        model.Params.Heuristics = 0.5  # Increased heuristics effort
        model.Params.Presolve = 2  # Aggressive presolve

        pre_stats: Dict[str, Any] = {}
        iis_generated = False

        builder = MILPModelBuilder()
        trip_by_id = problem.trip_by_id()
        dispatch_trip_by_id = problem.dispatch_context.trips_by_id()
        assignment_pairs = builder.enumerate_assignment_pairs(problem)
        arc_pairs = builder.enumerate_arc_pairs(problem, trip_by_id)
        vehicle_by_id = {
            str(vehicle.vehicle_id): vehicle
            for vehicle in problem.vehicles
        }
        assignment_trip_ids_by_vehicle: Dict[str, List[str]] = {}
        assignment_vehicle_ids_by_trip: Dict[str, List[str]] = {}
        startup_feasible_by_assignment: Dict[Tuple[str, str], bool] = {}
        startup_infeasible_trip_ids: Set[str] = set()
        startup_infeasible_vehicle_ids: Set[str] = set()
        for vehicle_id, trip_id in assignment_pairs:
            assignment_trip_ids_by_vehicle.setdefault(vehicle_id, []).append(trip_id)
            assignment_vehicle_ids_by_trip.setdefault(trip_id, []).append(vehicle_id)
            startup_feasible_by_assignment[(vehicle_id, trip_id)] = self._vehicle_can_start_trip(
                problem,
                vehicle_by_id.get(str(vehicle_id)),
                trip_by_id.get(str(trip_id)),
            )
            if not startup_feasible_by_assignment[(vehicle_id, trip_id)]:
                startup_infeasible_trip_ids.add(str(trip_id))
                startup_infeasible_vehicle_ids.add(str(vehicle_id))
        fixed_route_band_mode = bool(problem.metadata.get("fixed_route_band_mode", False))
        service_coverage_mode = normalize_service_coverage_mode(
            getattr(problem.scenario, "service_coverage_mode", None)
            or problem.metadata.get("service_coverage_mode", "strict")
        )
        allow_same_day_depot_cycles = bool(
            getattr(problem.scenario, "allow_same_day_depot_cycles", True)
        )
        daily_fragment_limit = self._safe_positive_int(
            problem.metadata.get("daily_fragment_limit")
            or problem.metadata.get("max_depot_cycles_per_vehicle_per_day")
            or getattr(problem.scenario, "max_depot_cycles_per_vehicle_per_day", 1),
            default=1,
        )
        if not allow_same_day_depot_cycles:
            daily_fragment_limit = 1
        trip_day_index_by_trip_id = {
            trip.trip_id: self._trip_day_index(problem, trip.departure_min)
            for trip in problem.trips
        }

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
        day_indices = sorted(set(trip_day_index_by_trip_id.values()))
        used_vehicle_day: Dict[Tuple[str, int], Any] = {
            (vehicle.vehicle_id, day_idx): model.addVar(vtype=GRB.BINARY)
            for vehicle in problem.vehicles
            for day_idx in day_indices
        }

        # Each trip must be assigned exactly once or marked as unserved.
        for trip in problem.trips:
            assign_terms = [y[(vehicle_id, trip.trip_id)] for vehicle_id in assignment_vehicle_ids_by_trip.get(trip.trip_id, [])]
            model.addConstr(gp.quicksum(assign_terms) + unserved[trip.trip_id] == 1)

        allow_partial_service = service_coverage_mode == "penalized"
        hard_no_unserved_constraints: List[Any] = []
        if not allow_partial_service:
            for trip in problem.trips:
                hard_no_unserved_constraints.append(model.addConstr(unserved[trip.trip_id] == 0))

        # Vehicle-use linkage.
        for (vehicle_id, trip_id), var in y.items():
            model.addConstr(var <= used_vehicle[vehicle_id])
        for vehicle in problem.vehicles:
            if not bool(getattr(vehicle, "available", True)):
                model.addConstr(used_vehicle[vehicle.vehicle_id] == 0)

        # Per-day vehicle usage linkage for multi-day constraints.
        for vehicle in problem.vehicles:
            vehicle_id = vehicle.vehicle_id
            for day_idx in day_indices:
                day_var = used_vehicle_day[(vehicle_id, day_idx)]
                day_trip_vars = [
                    y[(vehicle_id, trip_id)]
                    for trip_id in assignment_trip_ids_by_vehicle.get(vehicle_id, [])
                    if int(trip_day_index_by_trip_id.get(trip_id, 0)) == day_idx
                    and (vehicle_id, trip_id) in y
                ]
                if not day_trip_vars:
                    model.addConstr(day_var == 0)
                    continue
                for trip_var in day_trip_vars:
                    model.addConstr(trip_var <= day_var)
                model.addConstr(day_var <= gp.quicksum(day_trip_vars))
                model.addConstr(day_var <= used_vehicle[vehicle_id])

        outgoing_by_node: Dict[Tuple[str, str], List[Any]] = {}
        incoming_by_node: Dict[Tuple[str, str], List[Any]] = {}
        for (vehicle_id, from_trip_id, to_trip_id), var in x.items():
            outgoing_by_node.setdefault((vehicle_id, from_trip_id), []).append(var)
            incoming_by_node.setdefault((vehicle_id, to_trip_id), []).append(var)
            if (vehicle_id, from_trip_id) in y:
                model.addConstr(var <= y[(vehicle_id, from_trip_id)])
            if (vehicle_id, to_trip_id) in y:
                model.addConstr(var <= y[(vehicle_id, to_trip_id)])
        for key, var in start_arc.items():
            if not startup_feasible_by_assignment.get(key, True):
                model.addConstr(var == 0)

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
            for trip_id in assignment_trip_ids_by_vehicle.get(vehicle.vehicle_id, []):
                key = (vehicle.vehicle_id, trip_id)
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
            for day_idx in day_indices:
                day_trip_ids = [
                    trip_id
                    for trip_id in assignment_trip_ids_by_vehicle.get(vehicle.vehicle_id, [])
                    if int(trip_day_index_by_trip_id.get(trip_id, 0)) == day_idx
                ]
                if not day_trip_ids:
                    continue
                model.addConstr(
                    gp.quicksum(
                        start_arc[(vehicle.vehicle_id, trip_id)]
                        for trip_id in day_trip_ids
                        if (vehicle.vehicle_id, trip_id) in start_arc
                    )
                    <= daily_fragment_limit
                )
                model.addConstr(
                    gp.quicksum(
                        end_arc[(vehicle.vehicle_id, trip_id)]
                        for trip_id in day_trip_ids
                        if (vehicle.vehicle_id, trip_id) in end_arc
                    )
                    <= daily_fragment_limit
                )

        self._add_fragment_pairwise_depot_reset_cuts(
            model,
            trip_by_id=trip_by_id,
            vehicles=problem.vehicles,
            assignment_trip_ids_by_vehicle=assignment_trip_ids_by_vehicle,
            start_arc=start_arc,
            end_arc=end_arc,
            trip_day_index_by_trip_id=trip_day_index_by_trip_id,
            problem=problem,
            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            fixed_route_band_mode=fixed_route_band_mode,
        )

        # Fixed route-band mode is enforced on connection arcs, not across the
        # whole vehicle-day. A vehicle may switch bands only by starting a new
        # fragment; direct cross-band chaining remains forbidden.
        if fixed_route_band_mode:
            pass

        # C5: enforce exact minute-level interval occupancy. Hourly/price slots
        # are too coarse and can incorrectly block back-to-back trips within the
        # same slot, which makes a truthful full-service baseline infeasible.
        overlap_cliques = self._build_trip_overlap_cliques(problem)
        if overlap_cliques:
            for vehicle in problem.vehicles:
                vehicle_id = vehicle.vehicle_id
                for clique_trip_ids in overlap_cliques:
                    terms = [
                        y[(vehicle_id, trip_id)]
                        for trip_id in clique_trip_ids
                        if (vehicle_id, trip_id) in y
                    ]
                    if len(terms) <= 1:
                        continue
                    model.addConstr(gp.quicksum(terms) <= 1)

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
                trip_energy_kwh = self._trip_energy_kwh(problem, vehicle, trip.trip_id)
                if trip_energy_kwh <= 0.0:
                    continue
                # Event-based accounting: consume trip energy at the trip-end slot.
                event_slot_idx = self._trip_event_slot_index(
                    problem,
                    trip.departure_min,
                    trip.arrival_min,
                )
                electric_trip_kwh_by_slot.setdefault(event_slot_idx, []).append((trip_energy_kwh, key))
            for vehicle_id, from_trip_id, to_trip_id in arc_pairs:
                if vehicle_id != vehicle.vehicle_id:
                    continue
                deadhead_kwh = self._deadhead_energy_kwh(
                    problem,
                    vehicle,
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
        pv2bus_var: Dict[Tuple[str, int], Any] = {}
        g2bess_var: Dict[Tuple[str, int], Any] = {}
        pv2bess_var: Dict[Tuple[str, int], Any] = {}
        bess2bus_var: Dict[Tuple[str, int], Any] = {}
        pv_curt_var: Dict[Tuple[str, int], Any] = {}
        bess_soc_var: Dict[Tuple[str, int], Any] = {}
        grid_import_var: Dict[Tuple[str, int], Any] = {}
        contract_over_limit_var: Dict[Tuple[str, int], Any] = {}
        p_avg_depot_var: Dict[Tuple[str, int], Any] = {}
        w_on_depot_var: Dict[str, Any] = {}
        w_off_depot_var: Dict[str, Any] = {}
        bess_charge_mode_var: Dict[Tuple[str, int], Any] = {}
        bess_discharge_mode_var: Dict[Tuple[str, int], Any] = {}
        end_soc_excess_dev_var: Dict[str, Any] = {}
        charge_session_start_var: Dict[Tuple[str, int], Any] = {}
        soc_upper_excess_var: Dict[Tuple[str, int], Any] = {}
        slot_concurrency_excess_var: Dict[Tuple[str, int], Any] = {}
        charge_ports_by_depot: Dict[str, float] = {}
        w_on_var = None
        w_off_var = None
        effective_depot_energy_assets: Dict[str, DepotEnergyAsset] = {}

        home_depot_slot_proxy_terms: Dict[Tuple[str, int], List[Any]] = {}
        charging_window_mode = str(
            problem.metadata.get("charging_window_mode") or "timetable_layover"
        ).strip().lower()
        if charging_window_mode not in {"home_depot_proxy", "timetable_layover"}:
            charging_window_mode = "timetable_layover"
        # Relaxed charging window: 2x timestep for better feasibility
        default_charge_window = float(max(problem.scenario.timestep_min, 1)) * 2.0
        pre_window_min = self._safe_nonnegative_float(
            problem.metadata.get("home_depot_charge_pre_window_min"),
            default=default_charge_window,
        )
        post_window_min = self._safe_nonnegative_float(
            problem.metadata.get("home_depot_charge_post_window_min"),
            default=default_charge_window,
        )
        operation_start_min = self._operation_start_min(problem)
        operation_end_min = self._operation_end_min(problem)
        planning_days = max(int(problem.metadata.get("planning_days") or problem.scenario.planning_days or 1), 1)
        if slot_indices:
            first_slot_idx = slot_indices[0]
            last_slot_idx = slot_indices[-1]
            for vehicle in problem.vehicles:
                vehicle_id = vehicle.vehicle_id
                home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "depot_default")
                for trip in problem.trips:
                    key = (vehicle_id, trip.trip_id)
                    if key not in y:
                        continue
                    if str(trip.origin) != home_depot_id and str(trip.destination) != home_depot_id:
                        continue
                    candidate_slots: Set[int] = set()
                    if charging_window_mode == "home_depot_proxy":
                        dep_slot_idx = self._slot_index(problem, trip.departure_min)
                        arr_slot_idx = self._trip_event_slot_index(problem, trip.departure_min, trip.arrival_min)
                        candidate_slots.update(
                            {
                                dep_slot_idx,
                                max(dep_slot_idx - 1, first_slot_idx),
                                arr_slot_idx,
                                min(arr_slot_idx + 1, last_slot_idx),
                            }
                        )
                    else:
                        candidate_slots.update(
                            self._collect_home_depot_window_slots(
                                problem,
                                trip,
                                home_depot_id=home_depot_id,
                                pre_window_min=pre_window_min,
                                post_window_min=post_window_min,
                            )
                        )
                        if not candidate_slots:
                            # Keep backward compatibility when no explicit window can be derived.
                            dep_slot_idx = self._slot_index(problem, trip.departure_min)
                            arr_slot_idx = self._trip_event_slot_index(problem, trip.departure_min, trip.arrival_min)
                            candidate_slots.update(
                                {
                                    dep_slot_idx,
                                    max(dep_slot_idx - 1, first_slot_idx),
                                    arr_slot_idx,
                                    min(arr_slot_idx + 1, last_slot_idx),
                                }
                            )
                    for slot_idx in candidate_slots:
                        if slot_idx < first_slot_idx or slot_idx > last_slot_idx:
                            continue
                        home_depot_slot_proxy_terms.setdefault((vehicle_id, slot_idx), []).append(y[key])
                for day_idx in range(max(planning_days - 1, 0)):
                    overnight_slots = self._collect_overnight_home_depot_slots(
                        problem,
                        day_idx=day_idx,
                        operation_start_min=operation_start_min,
                        operation_end_min=operation_end_min,
                    )
                    day_use_var = used_vehicle_day.get((vehicle_id, day_idx))
                    if day_use_var is None:
                        continue
                    for slot_idx in overnight_slots:
                        if slot_idx < first_slot_idx or slot_idx > last_slot_idx:
                            continue
                        home_depot_slot_proxy_terms.setdefault((vehicle_id, slot_idx), []).append(
                            day_use_var
                        )

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
                if problem.chargers:
                    # Charger assignment is aggregated in this model, so use the strongest
                    # available charger as the charger-side per-vehicle cap.
                    max_charger_kw = max(float(charger.power_kw or 0.0) for charger in problem.chargers)
                    if max_charger_kw > 0.0:
                        charge_max_kw = min(charge_max_kw, max_charger_kw)
                discharge_max_kw = self._discharge_power_max_kw(problem, vehicle.vehicle_type)

                for slot_idx in slot_indices:
                    charge_on_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(vtype=GRB.BINARY)
                    charge_session_start_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(vtype=GRB.BINARY)
                    c_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(lb=0.0, ub=charge_max_kw, vtype=GRB.CONTINUOUS)
                    d_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(lb=0.0, ub=discharge_max_kw, vtype=GRB.CONTINUOUS)
                    # Soft SOC bounds: allow violations with penalty
                    s_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(lb=0.0, ub=cap * 1.2, vtype=GRB.CONTINUOUS)
                    # Penalty variables for SOC bound violations
                    soc_deficit_key = (vehicle.vehicle_id, slot_idx, "lower")
                    soc_excess_key = (vehicle.vehicle_id, slot_idx, "upper")
                    soc_lower_deficit = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"soc_deficit_{vehicle.vehicle_id}_{slot_idx}")
                    soc_upper_excess = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"soc_excess_{vehicle.vehicle_id}_{slot_idx}")
                    soc_upper_excess_var[soc_excess_key] = soc_upper_excess  # Store for objective
                    soc_upper_excess_var[soc_deficit_key] = soc_lower_deficit  # Store for objective (reuse dict)
                    # Add soft constraints
                    model.addConstr(s_var[(vehicle.vehicle_id, slot_idx)] + soc_lower_deficit >= soc_min)
                    model.addConstr(s_var[(vehicle.vehicle_id, slot_idx)] - soc_upper_excess <= cap)

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

                # C11: terminal SOC lower bound.
                last_slot = slot_indices[-1]
                final_soc_floor_kwh = soc_min
                if final_soc_floor_ratio_override is not None:
                    final_soc_floor_kwh = max(final_soc_floor_kwh, final_soc_floor_ratio_override * cap)
                model.addConstr(
                    s_var[(vehicle.vehicle_id, last_slot)]
                    >= final_soc_floor_kwh * used_vehicle[vehicle.vehicle_id]
                )

                # Apply day-end SOC floor/target for each planning day to support multi-day overnight operations.
                for day_idx in day_indices:
                    day_slot_idx = self._day_end_slot_index(
                        problem,
                        day_idx=day_idx,
                        operation_start_min=operation_start_min,
                        operation_end_min=operation_end_min,
                    )
                    day_soc_key = (vehicle.vehicle_id, day_slot_idx)
                    if day_soc_key not in s_var:
                        continue
                    day_use_var = used_vehicle_day.get((vehicle.vehicle_id, day_idx))
                    if day_use_var is None:
                        day_use_var = used_vehicle[vehicle.vehicle_id]
                    model.addConstr(
                        s_var[day_soc_key] >= final_soc_floor_kwh * day_use_var
                    )

                    if final_soc_target_ratio_override is not None:
                        target_kwh = min(max(final_soc_target_ratio_override * cap, soc_min), cap)
                        tolerance_ratio = 0.0
                        if final_soc_target_tolerance_ratio_override is not None:
                            tolerance_ratio = min(max(final_soc_target_tolerance_ratio_override, 0.0), 1.0)
                        tolerance_kwh = tolerance_ratio * cap
                        excess_dev = model.addVar(lb=0.0, ub=cap, vtype=GRB.CONTINUOUS)
                        end_soc_excess_dev_var[f"{vehicle.vehicle_id}__d{day_idx}"] = excess_dev
                        model.addConstr(
                            excess_dev
                            >= s_var[day_soc_key]
                            - (target_kwh + tolerance_kwh)
                            - cap * (1 - day_use_var)
                        )
                        model.addConstr(
                            excess_dev
                            >= (target_kwh - tolerance_kwh)
                            - s_var[day_soc_key]
                            - cap * (1 - day_use_var)
                        )

                upper_buffer_ratio = self._percent_to_ratio(
                    problem.metadata.get("charge_upper_buffer_ratio")
                )
                if upper_buffer_ratio is not None:
                    upper_buffer_kwh = min(max(upper_buffer_ratio * cap, soc_min), cap)
                    for slot_idx in slot_indices:
                        excess_key = (vehicle.vehicle_id, slot_idx)
                        soc_upper_excess_var[excess_key] = model.addVar(lb=0.0, ub=cap, vtype=GRB.CONTINUOUS)
                        model.addConstr(
                            soc_upper_excess_var[excess_key]
                            >= s_var[excess_key]
                            - upper_buffer_kwh
                            - cap * (1 - used_vehicle[vehicle.vehicle_id])
                        )

                # C10 (departure readiness): each assigned BEV trip must start with sufficient SOC.
                for trip in problem.trips:
                    key = (vehicle.vehicle_id, trip.trip_id)
                    if key not in y:
                        continue
                    depart_slot_idx = self._slot_index(problem, trip.departure_min)
                    if (vehicle.vehicle_id, depart_slot_idx) not in s_var:
                        continue
                    required_departure_kwh = self._required_departure_soc_kwh(
                        problem,
                        vehicle,
                        trip,
                        cap_kwh=cap,
                        final_soc_floor_kwh=final_soc_floor_kwh,
                    )
                    if required_departure_kwh <= 0.0:
                        continue
                    model.addConstr(
                        s_var[(vehicle.vehicle_id, depart_slot_idx)]
                        >= required_departure_kwh * y[key]
                    )

                for pos in range(len(slot_indices) - 1):
                    slot_idx = slot_indices[pos]
                    next_slot_idx = slot_indices[pos + 1]
                    # Slot-spread SOC update: distribute trip energy proportionally
                    # across all slots where the trip is active. This prevents hidden
                    # mid-trip SOC violations where a vehicle appears safe at trip-end
                    # but actually goes below minimum SOC mid-trip.
                    #
                    # For a trip spanning multiple slots, each slot contributes:
                    #   trip_energy * (overlap_duration / trip_duration)
                    # This ensures mid-trip SOC is checked, not just end-trip SOC.
                    trip_energy_expr = gp.quicksum(
                        self._trip_energy_kwh(problem, vehicle, trip.trip_id)
                        * self._trip_slot_energy_fraction(
                            problem,
                            trip.departure_min,
                            trip.arrival_min,
                            slot_idx,
                        )
                        * y[(vehicle.vehicle_id, trip.trip_id)]
                        for trip in problem.trips
                        if (vehicle.vehicle_id, trip.trip_id) in y
                        and self._trip_active_in_slot(
                            problem,
                            trip.departure_min,
                            trip.arrival_min,
                            slot_idx,
                        )
                    )
                    # C8: deadhead energy consumption linked with selected connection arcs.
                    deadhead_energy_expr = gp.quicksum(
                        self._deadhead_energy_kwh(problem, vehicle, from_trip_id, to_trip_id)
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
                    proxy_terms = home_depot_slot_proxy_terms.get((vehicle.vehicle_id, slot_idx), [])
                    if proxy_terms:
                        # Depot-stay approximation: allow charging only around assigned trips
                        # that touch the vehicle's home depot.
                        model.addConstr(
                            charge_on_var[(vehicle.vehicle_id, slot_idx)] <= gp.quicksum(proxy_terms)
                        )
                    model.addConstr(
                        c_var[(vehicle.vehicle_id, slot_idx)]
                        <= charge_max_kw * charge_on_var[(vehicle.vehicle_id, slot_idx)]
                    )

                    prev_slot_idx = slot_indices[pos - 1] if pos > 0 else None
                    start_key = (vehicle.vehicle_id, slot_idx)
                    if prev_slot_idx is None:
                        model.addConstr(
                            charge_session_start_var[start_key]
                            >= charge_on_var[start_key]
                        )
                    else:
                        model.addConstr(
                            charge_session_start_var[start_key]
                            >= charge_on_var[start_key] - charge_on_var[(vehicle.vehicle_id, prev_slot_idx)]
                        )

            if problem.chargers:
                ports_by_depot: Dict[str, float] = {}
                kw_by_depot: Dict[str, float] = {}
                for charger in problem.chargers:
                    depot_id = str(charger.depot_id or "depot_default")
                    ports = max(int(charger.simultaneous_ports or 1), 1)
                    power_kw = max(float(charger.power_kw or 0.0), 0.0)
                    ports_by_depot[depot_id] = ports_by_depot.get(depot_id, 0.0) + float(ports)
                    kw_by_depot[depot_id] = kw_by_depot.get(depot_id, 0.0) + power_kw * float(ports)
                charge_ports_by_depot = dict(ports_by_depot)

                vehicle_by_id = {v.vehicle_id: v for v in problem.vehicles}
                bev_ids_by_depot_for_charge: Dict[str, List[str]] = {}
                for vehicle_id in bev_ids:
                    vehicle = vehicle_by_id.get(vehicle_id)
                    depot_id = str(getattr(vehicle, "home_depot_id", "") or "depot_default")
                    bev_ids_by_depot_for_charge.setdefault(depot_id, []).append(vehicle_id)

                for slot_idx in slot_indices:
                    for depot_id, vehicle_ids in bev_ids_by_depot_for_charge.items():
                        port_limit = float(ports_by_depot.get(depot_id, 0.0))
                        kw_limit = float(kw_by_depot.get(depot_id, 0.0))
                        model.addConstr(
                            gp.quicksum(charge_on_var[(vehicle_id, slot_idx)] for vehicle_id in vehicle_ids)
                            <= port_limit
                        )
                        model.addConstr(
                            gp.quicksum(c_var[(vehicle_id, slot_idx)] for vehicle_id in vehicle_ids)
                            <= kw_limit
                        )
                        soft_ratio = self._safe_nonnegative_float(
                            problem.metadata.get("charge_concurrency_soft_limit_ratio"),
                            default=0.7,
                        )
                        soft_limit = self._soft_charge_concurrency_limit(port_limit, soft_ratio)
                        excess_key = (depot_id, slot_idx)
                        slot_concurrency_excess_var[excess_key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                        model.addConstr(
                            slot_concurrency_excess_var[excess_key]
                            >= gp.quicksum(charge_on_var[(vehicle_id, slot_idx)] for vehicle_id in vehicle_ids)
                            - float(soft_limit)
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
                    proxy_terms = home_depot_slot_proxy_terms.get((vehicle.vehicle_id, slot_idx), [])
                    if proxy_terms:
                        model.addConstr(
                            refuel_l_var[(vehicle.vehicle_id, slot_idx)]
                            <= max(refuel_per_slot_l, 0.0) * gp.quicksum(proxy_terms)
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
            enable_contract_overage_penalty = bool(
                problem.metadata.get("enable_contract_overage_penalty", True)
            )
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
            effective_depot_energy_assets = depot_energy_assets

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
                    pv2bus_var[key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
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
                    model.addConstr(bess2bus_var[key] + g2bus_var[key] + pv2bus_var[key] == charge_kwh_expr)

                    pv_gen_kwh = 0.0
                    if asset.pv_enabled and asset.pv_generation_kwh_by_slot:
                        pos = slot_indices.index(slot_idx)
                        if pos < len(asset.pv_generation_kwh_by_slot):
                            pv_gen_kwh = max(float(asset.pv_generation_kwh_by_slot[pos] or 0.0), 0.0)
                    model.addConstr(pv2bus_var[key] + pv2bess_var[key] + pv_curt_var[key] == pv_gen_kwh)

                    model.addConstr(grid_import_var[key] == g2bus_var[key] + g2bess_var[key])
                    if enable_contract_overage_penalty:
                        contract_over_limit_var[key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                        model.addConstr(
                            grid_import_var[key]
                            <= contract_limit_kw * timestep_h + contract_over_limit_var[key]
                        )
                    else:
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

        component_flags = normalize_cost_component_flags(
            problem.metadata.get("cost_component_flags")
        )
        unserved_penalty_weight = max(problem.objective_weights.unserved, 0.0)
        objective_mode = normalize_objective_mode(problem.scenario.objective_mode)
        energy_weight = max(problem.objective_weights.energy, 0.0)
        demand_weight = max(problem.objective_weights.demand, 0.0)
        vehicle_weight = max(problem.objective_weights.vehicle, 0.0)
        charge_session_start_penalty = self._safe_nonnegative_float(
            problem.metadata.get("charge_session_start_penalty_yen"),
            default=2.0,
        )
        slot_concurrency_penalty = self._safe_nonnegative_float(
            problem.metadata.get("slot_concurrency_penalty_yen"),
            default=1.0,
        )
        early_charge_penalty_per_kwh = self._safe_nonnegative_float(
            problem.metadata.get("early_charge_penalty_yen_per_kwh"),
            default=0.5,
        )
        charge_upper_buffer_penalty_per_kwh = self._safe_nonnegative_float(
            problem.metadata.get("charge_to_upper_buffer_penalty_yen_per_kwh"),
            default=0.2,
        )

        objective = gp.LinExpr()
        # O2: electricity cost based on actual charging source flows.
        price_by_slot = {slot.slot_index: slot.grid_buy_yen_per_kwh for slot in problem.price_slots}
        grid_to_bus_priority_penalty = self._safe_nonnegative_float(
            problem.metadata.get("grid_to_bus_priority_penalty_yen_per_kwh"),
            default=10.0,
        )
        grid_to_bess_priority_penalty = self._safe_nonnegative_float(
            problem.metadata.get("grid_to_bess_priority_penalty_yen_per_kwh"),
            default=2.0,
        )
        contract_overage_penalty = self._safe_nonnegative_float(
            problem.metadata.get("contract_overage_penalty_yen_per_kwh"),
            default=500.0,
        )
        curtail_penalty = self._safe_nonnegative_float(
            problem.metadata.get("pv_curtail_penalty_yen_per_kwh"),
            default=0.0,
        )
        if g2bus_var or g2bess_var or bess2bus_var:
            if component_flags.get("electricity_cost", True):
                for (depot_id, slot_idx), var in g2bus_var.items():
                    price = max(float(price_by_slot.get(slot_idx, 0.0) or 0.0), 0.0)
                    objective += energy_weight * price * var
                    asset = effective_depot_energy_assets.get(depot_id)
                    if (
                        asset is not None
                        and asset.bess_enabled
                        and grid_to_bus_priority_penalty > 0.0
                        and component_flags.get("grid_to_bus_priority_penalty", True)
                    ):
                        objective += energy_weight * grid_to_bus_priority_penalty * var
                for (depot_id, slot_idx), var in g2bess_var.items():
                    price = max(float(price_by_slot.get(slot_idx, 0.0) or 0.0), 0.0)
                    objective += energy_weight * price * var
                    asset = effective_depot_energy_assets.get(depot_id)
                    if (
                        asset is not None
                        and asset.bess_enabled
                        and grid_to_bess_priority_penalty > 0.0
                        and component_flags.get("grid_to_bess_priority_penalty", True)
                    ):
                        objective += energy_weight * grid_to_bess_priority_penalty * var
                for (depot_id, slot_idx), var in bess2bus_var.items():
                    asset = effective_depot_energy_assets.get(depot_id) or (problem.depot_energy_assets or {}).get(depot_id)
                    bess_marginal = max(float(getattr(asset, "bess_cycle_cost_yen_per_kwh", 0.0) or 0.0), 0.0)
                    objective += energy_weight * bess_marginal * var
            if curtail_penalty > 0.0 and component_flags.get("electricity_cost", True):
                for var in pv_curt_var.values():
                    objective += energy_weight * curtail_penalty * var
            if contract_overage_penalty > 0.0 and component_flags.get("contract_overage_penalty", True):
                for var in contract_over_limit_var.values():
                    objective += contract_overage_penalty * var
        else:
            # Backward-compatible fallback for plans without charging-source variables.
            if component_flags.get("electricity_cost", True):
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
        if component_flags.get("fuel_cost", True):
            for (vehicle_id, trip_id), var in y.items():
                vehicle = next((v for v in problem.vehicles if v.vehicle_id == vehicle_id), None)
                if vehicle is None or vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}:
                    continue
                trip = trip_by_id.get(trip_id)
                if trip is None:
                    continue
                fuel_l = self._trip_fuel_l(problem, vehicle, trip_id)
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
        if (
            component_flags.get("demand_charge_cost", True)
            and w_on_var is not None
            and w_off_var is not None
        ):
            objective += demand_weight * max(problem.scenario.demand_charge_on_peak_yen_per_kw, 0.0) * w_on_var
            objective += demand_weight * max(problem.scenario.demand_charge_off_peak_yen_per_kw, 0.0) * w_off_var

        if component_flags.get("vehicle_fixed_cost", True):
            for vehicle in problem.vehicles:
                objective += vehicle_weight * vehicle.fixed_use_cost_jpy * used_vehicle[vehicle.vehicle_id]

        if component_flags.get("driver_cost", True):
            regular_shift_minutes = _DRIVER_REGULAR_HOURS_PER_DAY * 60.0
            driver_base_cost_per_minute = _DRIVER_WAGE_JPY_PER_H / 60.0
            driver_overtime_surcharge_per_minute = (
                _DRIVER_WAGE_JPY_PER_H * (_DRIVER_OVERTIME_FACTOR - 1.0) / 60.0
            )
            for vehicle in problem.vehicles:
                vehicle_id = vehicle.vehicle_id
                for day_idx in day_indices:
                    day_trip_ids = [
                        trip_id
                        for trip_id in assignment_trip_ids_by_vehicle.get(vehicle_id, [])
                        if int(trip_day_index_by_trip_id.get(trip_id, 0)) == day_idx
                    ]
                    if not day_trip_ids:
                        continue
                    day_start_expr = gp.quicksum(
                        trip_by_id[trip_id].departure_min * start_arc[(vehicle_id, trip_id)]
                        for trip_id in day_trip_ids
                        if (vehicle_id, trip_id) in start_arc
                    )
                    day_end_expr = gp.quicksum(
                        trip_by_id[trip_id].arrival_min * end_arc[(vehicle_id, trip_id)]
                        for trip_id in day_trip_ids
                        if (vehicle_id, trip_id) in end_arc
                    )
                    day_start_count = gp.quicksum(
                        start_arc[(vehicle_id, trip_id)]
                        for trip_id in day_trip_ids
                        if (vehicle_id, trip_id) in start_arc
                    )
                    day_overtime_min = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                    model.addConstr(
                        day_overtime_min
                        >= day_end_expr - day_start_expr + _DRIVER_PREP_TIME_MIN * day_start_count
                        - regular_shift_minutes * day_start_count
                    )
                    objective += driver_base_cost_per_minute * (
                        day_end_expr - day_start_expr + _DRIVER_PREP_TIME_MIN * day_start_count
                    )
                    objective += driver_overtime_surcharge_per_minute * day_overtime_min

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
                fuel_l = self._trip_fuel_l(problem, vehicle, trip_id)
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
            if component_flags.get("final_soc_target_penalty", True):
                for dev in end_soc_excess_dev_var.values():
                    objective += target_penalty_per_kwh * dev

        if charge_session_start_penalty > 0.0 and component_flags.get("charge_session_start_penalty", True):
            for var in charge_session_start_var.values():
                objective += charge_session_start_penalty * var

        if slot_concurrency_penalty > 0.0 and component_flags.get("slot_concurrency_penalty", True):
            for var in slot_concurrency_excess_var.values():
                objective += slot_concurrency_penalty * var

        if (
            early_charge_penalty_per_kwh > 0.0
            and c_var
            and component_flags.get("early_charge_penalty", True)
        ):
            for (vehicle_id, slot_idx), var in c_var.items():
                early_weight = self._early_charge_weight(slot_idx, slot_indices)
                if early_weight <= 0.0:
                    continue
                objective += early_charge_penalty_per_kwh * early_weight * timestep_h * var

        if (
            charge_upper_buffer_penalty_per_kwh > 0.0
            and soc_upper_excess_var
            and component_flags.get("soc_upper_buffer_penalty", True)
        ):
            for var in soc_upper_excess_var.values():
                objective += charge_upper_buffer_penalty_per_kwh * var
        
        # SOC bound violation penalty (moderate penalty for better solvability)
        soc_violation_penalty_per_kwh = self._safe_nonnegative_float(
            problem.metadata.get("soc_violation_penalty_per_kwh"),
            default=1000.0,  # Moderate penalty to balance feasibility and solution quality
        )
        if soc_violation_penalty_per_kwh > 0.0 and component_flags.get("soc_violation_penalty", True):
            for key, var in soc_upper_excess_var.items():
                # Check if this is a violation variable (tuples with 3 elements)
                if isinstance(key, tuple) and len(key) == 3:
                    objective += soc_violation_penalty_per_kwh * var

        if (
            service_coverage_mode == "penalized"
            and component_flags.get("unserved_penalty", True)
            and unserved_penalty_weight > 0.0
        ):
            # Gradient unserved penalty: higher for peak hours, lower for off-peak
            for trip in problem.trips:
                trip_hour = trip.departure_min / 60.0
                # Peak hours (7-9, 17-19): 2x penalty; off-peak: 1x penalty
                is_peak = (7 <= trip_hour < 9) or (17 <= trip_hour < 19)
                penalty_multiplier = 2.0 if is_peak else 1.0
                objective += unserved_penalty_weight * penalty_multiplier * unserved[trip.trip_id]

        if getattr(config, "warm_start", True) and problem.baseline_plan is not None:
            baseline_plan = self._repaired_baseline_plan_for_warm_start(problem)
            baseline_duty_vehicle_map = baseline_plan.duty_vehicle_map()
            baseline_served_trip_ids: Set[str] = set()
            baseline_used_vehicle_ids: Set[str] = set()
            baseline_used_vehicle_days: Set[Tuple[str, int]] = set()
            baseline_charge_kw_by_key: Dict[Tuple[str, int], float] = {}
            baseline_refuel_l_by_key: Dict[Tuple[str, int], float] = {}

            for slot in baseline_plan.charging_slots:
                key = (str(slot.vehicle_id), int(slot.slot_index))
                baseline_charge_kw_by_key[key] = baseline_charge_kw_by_key.get(key, 0.0) + max(
                    float(slot.charge_kw or 0.0),
                    0.0,
                )
            for slot in baseline_plan.refuel_slots:
                key = (str(slot.vehicle_id), int(slot.slot_index))
                baseline_refuel_l_by_key[key] = baseline_refuel_l_by_key.get(key, 0.0) + max(
                    float(slot.refuel_liters or 0.0),
                    0.0,
                )

            for duty in baseline_plan.duties:
                vehicle_id = baseline_duty_vehicle_map.get(duty.duty_id, duty.duty_id)
                if vehicle_id not in used_vehicle:
                    continue
                baseline_used_vehicle_ids.add(vehicle_id)
                previous_trip_id: Optional[str] = None
                for leg in duty.legs:
                    trip_id = leg.trip.trip_id
                    baseline_served_trip_ids.add(trip_id)
                    trip_var = y.get((vehicle_id, trip_id))
                    if trip_var is not None:
                        trip_var.Start = 1.0
                    unserved_var = unserved.get(trip_id)
                    if unserved_var is not None:
                        unserved_var.Start = 0.0
                    day_idx = int(trip_day_index_by_trip_id.get(trip_id, 0))
                    baseline_used_vehicle_days.add((vehicle_id, day_idx))
                    if previous_trip_id is not None:
                        arc_var = x.get((vehicle_id, previous_trip_id, trip_id))
                        if arc_var is not None:
                            arc_var.Start = 1.0
                    previous_trip_id = trip_id

                if duty.legs:
                    first_trip_id = duty.legs[0].trip.trip_id
                    last_trip_id = duty.legs[-1].trip.trip_id
                    start_var = start_arc.get((vehicle_id, first_trip_id))
                    if start_var is not None:
                        start_var.Start = 1.0
                    end_var = end_arc.get((vehicle_id, last_trip_id))
                    if end_var is not None:
                        end_var.Start = 1.0

            for trip in problem.trips:
                if trip.trip_id in baseline_served_trip_ids:
                    continue
                unserved_var = unserved.get(trip.trip_id)
                if unserved_var is not None:
                    unserved_var.Start = 1.0

            for vehicle in problem.vehicles:
                vehicle_id = vehicle.vehicle_id
                used_vehicle_var = used_vehicle.get(vehicle_id)
                if used_vehicle_var is not None:
                    used_vehicle_var.Start = 1.0 if vehicle_id in baseline_used_vehicle_ids else 0.0
                for day_idx in day_indices:
                    day_var = used_vehicle_day.get((vehicle_id, day_idx))
                    if day_var is not None:
                        day_var.Start = 1.0 if (vehicle_id, day_idx) in baseline_used_vehicle_days else 0.0

            for (vehicle_id, slot_idx), var in charge_on_var.items():
                charge_kw = baseline_charge_kw_by_key.get((vehicle_id, slot_idx))
                if charge_kw is None:
                    continue
                var.Start = 1.0 if charge_kw > 0.0 else 0.0
            for (vehicle_id, slot_idx), var in c_var.items():
                charge_kw = baseline_charge_kw_by_key.get((vehicle_id, slot_idx))
                if charge_kw is None:
                    continue
                var.Start = float(charge_kw)
            for (vehicle_id, slot_idx), var in refuel_l_var.items():
                refuel_l = baseline_refuel_l_by_key.get((vehicle_id, slot_idx))
                if refuel_l is None:
                    continue
                var.Start = float(refuel_l)

        model.setObjective(objective, GRB.MINIMIZE)
        
        # Define status_map early for diagnostics
        status_map = {
            GRB.OPTIMAL: "optimal",
            GRB.TIME_LIMIT: "time_limit",
            GRB.SUBOPTIMAL: "suboptimal",
            GRB.INFEASIBLE: "infeasible",
            GRB.INF_OR_UNBD: "inf_or_unbd",
            GRB.UNBOUNDED: "unbounded",
        }
        
        # Pre-optimization diagnostics
        pre_stats = {
            "num_vars": model.NumVars,
            "num_constrs": model.NumConstrs,
            "num_binary_vars": model.NumBinVars,
            "num_integer_vars": model.NumIntVars,
            "num_continuous_vars": model.NumVars - model.NumBinVars - model.NumIntVars,
            "num_assignment_pairs": len(assignment_pairs),
            "num_arc_pairs": len(arc_pairs),
            "num_trips": len(problem.trips),
            "num_vehicles": len(problem.vehicles),
            "time_limit_sec": config.time_limit_sec,
            "mip_gap": config.mip_gap,
        }
        if enable_milp_diagnostics:
            import json
            print(f"[MILP Diagnostics] Pre-optimization stats:")
            for key, val in pre_stats.items():
                print(f"  {key}: {val}")
            with open(os.path.join(diagnostic_output_dir, f"pre_stats_{int(time.time())}.json"), "w") as f:
                json.dump(pre_stats, f, indent=2)
        
        optimize_started_at = time.perf_counter()
        first_feasible_sec: Optional[float] = None

        def _capture_first_feasible(_model: Any, where: Any) -> None:
            nonlocal first_feasible_sec
            try:
                if where == GRB.Callback.MIPSOL and first_feasible_sec is None:
                    first_feasible_sec = time.perf_counter() - optimize_started_at
            except Exception:
                return

        model.optimize(_capture_first_feasible)
        
        # Post-optimization diagnostics
        if enable_milp_diagnostics:
            post_stats = {
                "status": model.Status,
                "status_name": status_map.get(model.Status, f"status_{model.Status}"),
                "sol_count": model.SolCount,
                "obj_val": model.ObjVal if model.SolCount > 0 else None,
                "obj_bound": model.ObjBound if hasattr(model, "ObjBound") else None,
                "mip_gap": model.MIPGap if hasattr(model, "MIPGap") and model.SolCount > 0 else None,
                "runtime_sec": model.Runtime,
                "node_count": model.NodeCount if hasattr(model, "NodeCount") else None,
            }
            print(f"[MILP Diagnostics] Post-optimization stats:")
            for key, val in post_stats.items():
                print(f"  {key}: {val}")
            with open(os.path.join(diagnostic_output_dir, f"post_stats_{int(time.time())}.json"), "w") as f:
                json.dump(post_stats, f, indent=2)
            
            # If infeasible, compute IIS (Irreducible Inconsistent Subsystem)
            if model.Status == GRB.INFEASIBLE:
                print("[MILP Diagnostics] Model is INFEASIBLE. Computing IIS...")
                try:
                    model.computeIIS()
                    iis_generated = True
                    iis_file = os.path.join(diagnostic_output_dir, f"infeasible_iis_{int(time.time())}.ilp")
                    model.write(iis_file)
                    print(f"[MILP Diagnostics] IIS written to: {iis_file}")
                    
                    # List conflicting constraints
                    print("[MILP Diagnostics] Conflicting constraints:")
                    iis_constrs = [c for c in model.getConstrs() if c.IISConstr]
                    for i, constr in enumerate(iis_constrs[:20]):  # Show first 20
                        print(f"  {i+1}. {constr.ConstrName}")
                    if len(iis_constrs) > 20:
                        print(f"  ... and {len(iis_constrs) - 20} more")
                except Exception as e:
                    print(f"[MILP Diagnostics] Failed to compute IIS: {e}")

        if model.Status == GRB.INF_OR_UNBD:
            # Distinguish infeasible from unbounded before deciding fallback behavior.
            model.Params.DualReductions = 0
            model.optimize(_capture_first_feasible)

        relaxed_partial_service = False

        solver_status = status_map.get(model.Status, f"status_{model.Status}")
        runtime_sec = float(getattr(model, "Runtime", 0.0) or 0.0)
        has_feasible_incumbent = bool(model.SolCount > 0)
        presolve_reduction_summary = {
            "initial_num_vars": int(pre_stats.get("num_vars", 0) or 0),
            "initial_num_constrs": int(pre_stats.get("num_constrs", 0) or 0),
            "initial_num_bin_vars": int(pre_stats.get("num_binary_vars", 0) or 0),
            "initial_num_int_vars": int(pre_stats.get("num_integer_vars", 0) or 0),
        }
        best_bound = None
        if hasattr(model, "ObjBound"):
            try:
                best_bound = float(model.ObjBound)
            except Exception:
                best_bound = None
        final_gap = None
        if has_feasible_incumbent and hasattr(model, "MIPGap"):
            try:
                final_gap = float(model.MIPGap)
            except Exception:
                final_gap = None
        nodes_explored = None
        if hasattr(model, "NodeCount"):
            try:
                nodes_explored = int(model.NodeCount)
            except Exception:
                nodes_explored = None
        warm_start_applied = bool(getattr(config, "warm_start", True) and problem.baseline_plan is not None)
        warm_start_source = (
            str((problem.baseline_plan.metadata or {}).get("source") or "")
            if problem.baseline_plan is not None
            else ""
        )
        common_outcome_kwargs = {
            "has_feasible_incumbent": has_feasible_incumbent,
            "incumbent_count": int(model.SolCount),
            "warm_start_applied": warm_start_applied,
            "warm_start_source": warm_start_source,
            "best_bound": best_bound,
            "final_gap": final_gap,
            "nodes_explored": nodes_explored,
            "runtime_sec": runtime_sec,
            "first_feasible_sec": first_feasible_sec,
            "presolve_reduction_summary": presolve_reduction_summary,
            "iis_generated": bool(iis_generated),
        }

        if (
            model.SolCount > 0
            and relaxed_partial_service
            and unserved_penalty_weight > 0.0
            and problem.baseline_plan is not None
            and len(problem.baseline_plan.served_trip_ids) > 0
        ):
            full_unserved_obj = unserved_penalty_weight * float(len(problem.trips))
            incumbent_obj = float(model.ObjVal)
            if incumbent_obj >= full_unserved_obj - 1.0e-6:
                baseline_fallback = self._baseline_fallback(
                    problem,
                    fallback_status="auto_relaxed_baseline",
                    source="dispatch_baseline_after_relax",
                    solver_status=solver_status,
                    relaxed_partial_service=True,
                )
                if baseline_fallback is not None:
                    return baseline_fallback

        if model.SolCount <= 0:
            if model.Status == GRB.TIME_LIMIT:
                baseline_fallback = self._baseline_fallback(
                    problem,
                    fallback_status="time_limit_baseline",
                    source="dispatch_baseline_after_time_limit_no_incumbent",
                    solver_status=solver_status,
                    relaxed_partial_service=bool(relaxed_partial_service),
                )
                if baseline_fallback is not None:
                    return baseline_fallback
            empty = AssignmentPlan(
                duties=(),
                charging_slots=(),
                served_trip_ids=(),
                unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips)),
                metadata={
                    "source": "milp_gurobi",
                    "status": solver_status,
                    "auto_relaxed_allow_partial_service": bool(relaxed_partial_service),
                    "service_coverage_mode": service_coverage_mode,
                    "allow_partial_service": bool(allow_partial_service),
                    "strict_coverage_enforced": service_coverage_mode == "strict",
                    "startup_infeasible_assignment_count": len(startup_infeasible_trip_ids),
                    "startup_infeasible_trip_ids": tuple(sorted(startup_infeasible_trip_ids)),
                    "startup_infeasible_vehicle_ids": tuple(sorted(startup_infeasible_vehicle_ids)),
                },
            )
            return (
                MILPSolverOutcome(
                    solver_status=solver_status,
                    used_backend=self.backend_name,
                    supports_exact_milp=True,
                    **common_outcome_kwargs,
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
        pv_to_bus_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        bess_to_bus_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        pv_to_bess_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        grid_to_bess_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        pv_curtail_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        bess_soc_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        contract_over_limit_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        for (depot_id, slot_idx), var in g2bus_var.items():
            grid_to_bus_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = max(_var_val(var), 0.0)
        for (depot_id, slot_idx), var in pv2bus_var.items():
            pv_to_bus_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = max(_var_val(var), 0.0)
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
        for (depot_id, slot_idx), var in contract_over_limit_var.items():
            contract_over_limit_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = max(_var_val(var), 0.0)

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
                    pv_kwh = float(pv_to_bus_kwh_by_depot_slot.get(depot_id, {}).get(slot_idx, 0.0) or 0.0)
                    grid_kwh = float(grid_to_bus_kwh_by_depot_slot.get(depot_id, {}).get(slot_idx, 0.0) or 0.0)
                    bess_ratio = min(max(bess_kwh / demand_kwh, 0.0), 1.0)
                    pv_ratio = min(max(pv_kwh / demand_kwh, 0.0), 1.0)
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
                    if pv_ratio > 0.0:
                        lat, lon = _depot_latlon(depot_id)
                        charging_slots.append(
                            ChargingSlot(
                                vehicle_id=vehicle_id,
                                slot_index=slot_idx,
                                charger_id=f"pv:{depot_id}",
                                charge_kw=vehicle_kw * pv_ratio,
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

        duty_vehicle_map: Dict[str, str] = {}
        duties, served_trip_ids, duty_vehicle_map = self._build_vehicle_duties_from_solution(
            problem=problem,
            trip_by_id=trip_by_id,
            dispatch_trip_by_id=dispatch_trip_by_id,
            y=y,
            x=x,
            start_arc=start_arc,
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
            pv_to_bus_kwh_by_depot_slot=pv_to_bus_kwh_by_depot_slot,
            bess_to_bus_kwh_by_depot_slot=bess_to_bus_kwh_by_depot_slot,
            pv_to_bess_kwh_by_depot_slot=pv_to_bess_kwh_by_depot_slot,
            grid_to_bess_kwh_by_depot_slot=grid_to_bess_kwh_by_depot_slot,
            pv_curtail_kwh_by_depot_slot=pv_curtail_kwh_by_depot_slot,
            bess_soc_kwh_by_depot_slot=bess_soc_kwh_by_depot_slot,
            contract_over_limit_kwh_by_depot_slot=contract_over_limit_kwh_by_depot_slot,
            served_trip_ids=tuple(sorted(served_set)),
            unserved_trip_ids=tuple(unserved_trip_ids),
            metadata={
                "source": "milp_gurobi",
                "status": solver_status,
                "objective_value": float(model.ObjVal),
                "duty_vehicle_map": duty_vehicle_map,
                "horizon_start": str(problem.scenario.horizon_start or "00:00"),
                "timestep_min": int(problem.scenario.timestep_min),
                "enable_contract_overage_penalty": bool(problem.metadata.get("enable_contract_overage_penalty", True)),
                "contract_overage_penalty_yen_per_kwh": contract_overage_penalty,
                "grid_to_bus_priority_penalty_yen_per_kwh": grid_to_bus_priority_penalty,
                "grid_to_bess_priority_penalty_yen_per_kwh": grid_to_bess_priority_penalty,
                "charge_session_start_penalty_yen": charge_session_start_penalty,
                "slot_concurrency_penalty_yen": slot_concurrency_penalty,
                "early_charge_penalty_yen_per_kwh": early_charge_penalty_per_kwh,
                "charge_to_upper_buffer_penalty_yen_per_kwh": charge_upper_buffer_penalty_per_kwh,
                "service_coverage_mode": service_coverage_mode,
                "allow_partial_service": bool(allow_partial_service),
                "strict_coverage_enforced": service_coverage_mode == "strict",
                "startup_infeasible_assignment_count": len(startup_infeasible_trip_ids),
                "startup_infeasible_trip_ids": tuple(sorted(startup_infeasible_trip_ids)),
                "startup_infeasible_vehicle_ids": tuple(sorted(startup_infeasible_vehicle_ids)),
            },
        )
        return (
            MILPSolverOutcome(
                solver_status=solver_status,
                used_backend=self.backend_name,
                supports_exact_milp=True,
                **common_outcome_kwargs,
            ),
            plan,
        )

    def _baseline_fallback(
        self,
        problem: CanonicalOptimizationProblem,
        *,
        fallback_status: str,
        source: str,
        solver_status: str,
        relaxed_partial_service: bool,
    ) -> Optional[Tuple[MILPSolverOutcome, AssignmentPlan]]:
        baseline_plan = self._repaired_baseline_plan_for_warm_start(problem)
        if baseline_plan is None or len(baseline_plan.served_trip_ids) <= 0:
            return None
        service_coverage_mode = normalize_service_coverage_mode(
            getattr(problem.scenario, "service_coverage_mode", None)
            or problem.metadata.get("service_coverage_mode", "strict")
        )
        if service_coverage_mode == "strict" and baseline_plan.unserved_trip_ids:
            return None
        baseline_meta = dict(baseline_plan.metadata or {})
        baseline_meta.update(
            {
                "source": source,
                "status": fallback_status,
                "milp_status": solver_status,
                "milp_backend": self.backend_name,
                "auto_relaxed_allow_partial_service": bool(relaxed_partial_service),
            }
        )
        return (
            MILPSolverOutcome(
                solver_status="BASELINE_FALLBACK",
                used_backend=self.backend_name,
                supports_exact_milp=False,
                has_feasible_incumbent=False,
                incumbent_count=0,
                warm_start_applied=False,
                warm_start_source=f"fallback_{fallback_status}",
                runtime_sec=0.0,
                fallback_reason=fallback_status,
            ),
            replace(
                baseline_plan,
                metadata=baseline_meta,
            ),
        )

    def _add_fragment_pairwise_depot_reset_cuts(
        self,
        model: Any,
        *,
        trip_by_id: Mapping[str, ProblemTrip],
        vehicles: Tuple[Any, ...],
        assignment_trip_ids_by_vehicle: Mapping[str, List[str]],
        start_arc: Mapping[Tuple[str, str], Any],
        end_arc: Mapping[Tuple[str, str], Any],
        trip_day_index_by_trip_id: Mapping[str, int],
        problem: CanonicalOptimizationProblem,
        allow_same_day_depot_cycles: bool,
        fixed_route_band_mode: bool,
    ) -> int:
        cut_count = 0
        for vehicle in vehicles:
            vehicle_id = str(getattr(vehicle, "vehicle_id", "") or "")
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "")
            trip_ids = list(assignment_trip_ids_by_vehicle.get(vehicle_id, ()))
            for end_trip_id in trip_ids:
                end_trip = trip_by_id.get(end_trip_id)
                if end_trip is None:
                    continue
                for start_trip_id in trip_ids:
                    if start_trip_id == end_trip_id:
                        continue
                    start_trip = trip_by_id.get(start_trip_id)
                    if start_trip is None:
                        continue
                    if int(trip_day_index_by_trip_id.get(end_trip_id, 0)) != int(
                        trip_day_index_by_trip_id.get(start_trip_id, 0)
                    ):
                        continue
                    if int(end_trip.arrival_min) > int(start_trip.departure_min):
                        continue
                    end_key = (vehicle_id, end_trip_id)
                    start_key = (vehicle_id, start_trip_id)
                    if end_key not in end_arc or start_key not in start_arc:
                        continue
                    diagnostic = fragment_transition_diagnostic(
                        VehicleDuty(
                            duty_id=f"{vehicle_id}__end_probe",
                            vehicle_type=str(getattr(vehicle, "vehicle_type", "")),
                            legs=(DutyLeg(trip=end_trip),),
                        ),
                        VehicleDuty(
                            duty_id=f"{vehicle_id}__start_probe",
                            vehicle_type=str(getattr(vehicle, "vehicle_type", "")),
                            legs=(DutyLeg(trip=start_trip),),
                        ),
                        home_depot_id=home_depot_id,
                        dispatch_context=problem.dispatch_context,
                        fixed_route_band_mode=fixed_route_band_mode,
                        allow_same_day_depot_cycles=allow_same_day_depot_cycles,
                    )
                    if diagnostic.depot_reset_ok:
                        continue
                    model.addConstr(end_arc[end_key] + start_arc[start_key] <= 1)
                    cut_count += 1
        return cut_count

    def _repaired_baseline_plan_for_warm_start(
        self,
        problem: CanonicalOptimizationProblem,
    ) -> AssignmentPlan:
        baseline_plan = problem.baseline_plan or AssignmentPlan()
        try:
            from src.optimization.alns.operators_repair import _with_recomputed_charging, soc_repair
        except Exception:
            return baseline_plan

        repaired_plan = _with_recomputed_charging(problem, baseline_plan)
        repaired_plan = soc_repair(problem, repaired_plan)
        return repaired_plan

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
        adjusted_arrival = arrival_min
        if adjusted_arrival <= departure_min:
            adjusted_arrival += 24 * 60
        adjusted_arrival = max(adjusted_arrival - 1, departure_min)
        end_idx = self._slot_index(problem, adjusted_arrival)
        if end_idx < start_idx:
            end_idx = start_idx
        return tuple(range(start_idx, end_idx + 1))

    def _collect_home_depot_window_slots(
        self,
        problem: CanonicalOptimizationProblem,
        trip: ProblemTrip,
        *,
        home_depot_id: str,
        pre_window_min: float,
        post_window_min: float,
    ) -> Tuple[int, ...]:
        slots: Set[int] = set()
        horizon_start_min = self._horizon_start_min(problem)
        dep = int(trip.departure_min)
        arr = int(trip.arrival_min)
        if arr <= dep:
            arr += 24 * 60

        if str(trip.origin) == home_depot_id:
            pre_min = max(int(round(pre_window_min)), 0)
            start = max(dep - pre_min, horizon_start_min)
            end = max(dep, start + 1)
            slots.update(self._slot_indices_for_interval(problem, start, end))

        if str(trip.destination) == home_depot_id:
            post_min = max(int(round(post_window_min)), 0)
            start = max(arr, horizon_start_min)
            end = max(start + post_min, start + 1)
            slots.update(self._slot_indices_for_interval(problem, start, end))

        return tuple(sorted(slots))

    def _collect_overnight_home_depot_slots(
        self,
        problem: CanonicalOptimizationProblem,
        *,
        day_idx: int,
        operation_start_min: int,
        operation_end_min: int,
    ) -> Tuple[int, ...]:
        horizon_start_min = self._horizon_start_min(problem)
        day_start = horizon_start_min + day_idx * 24 * 60
        end_offset = operation_end_min - operation_start_min
        if end_offset <= 0:
            end_offset += 24 * 60
        overnight_start = day_start + end_offset
        overnight_end = day_start + 24 * 60
        if overnight_end <= overnight_start:
            return ()
        return self._slot_indices_for_interval(problem, overnight_start, overnight_end)

    def _trip_day_index(self, problem: CanonicalOptimizationProblem, departure_min: int) -> int:
        horizon_start_min = self._horizon_start_min(problem)
        adjusted = int(departure_min)
        if adjusted < horizon_start_min:
            adjusted += 24 * 60
        return max((adjusted - horizon_start_min) // (24 * 60), 0)

    def _day_end_slot_index(
        self,
        problem: CanonicalOptimizationProblem,
        *,
        day_idx: int,
        operation_start_min: int,
        operation_end_min: int,
    ) -> int:
        horizon_start_min = self._horizon_start_min(problem)
        day_start = horizon_start_min + day_idx * 24 * 60
        end_offset = operation_end_min - operation_start_min
        if end_offset <= 0:
            end_offset += 24 * 60
        day_end_abs = day_start + end_offset - 1
        return self._slot_index(problem, day_end_abs)

    def _operation_start_min(self, problem: CanonicalOptimizationProblem) -> int:
        return self._horizon_start_min(problem)

    def _operation_end_min(self, problem: CanonicalOptimizationProblem) -> int:
        value = problem.metadata.get("operation_end_time")
        if value is None:
            value = problem.scenario.horizon_end
        try:
            hh, mm = str(value).split(":")
            return int(hh) * 60 + int(mm)
        except (ValueError, AttributeError):
            return self._operation_start_min(problem)

    def _build_vehicle_duties_from_solution(
        self,
        *,
        problem: CanonicalOptimizationProblem,
        trip_by_id: Dict[str, ProblemTrip],
        dispatch_trip_by_id: Dict[str, Any],
        y: Dict[Tuple[str, str], Any],
        x: Dict[Tuple[str, str, str], Any],
        start_arc: Dict[Tuple[str, str], Any],
    ) -> Tuple[List[VehicleDuty], List[str], Dict[str, str]]:
        duties: List[VehicleDuty] = []
        served_trip_ids: List[str] = []
        duty_vehicle_map: Dict[str, str] = {}

        for vehicle in problem.vehicles:
            vehicle_id = str(vehicle.vehicle_id)
            assigned_trip_ids = {
                trip.trip_id
                for trip in problem.trips
                if (vehicle_id, trip.trip_id) in y and self._binary_value(y[(vehicle_id, trip.trip_id)])
            }
            if not assigned_trip_ids:
                continue

            successor_by_trip: Dict[str, str] = {}
            predecessor_by_trip: Dict[str, str] = {}
            for v_id, from_trip_id, to_trip_id in x:
                if v_id != vehicle_id or not self._binary_value(x[(v_id, from_trip_id, to_trip_id)]):
                    continue
                if from_trip_id not in assigned_trip_ids or to_trip_id not in assigned_trip_ids:
                    continue
                successor_by_trip[from_trip_id] = to_trip_id
                predecessor_by_trip[to_trip_id] = from_trip_id

            start_trip_ids = [
                trip_id
                for trip_id in assigned_trip_ids
                if (vehicle_id, trip_id) in start_arc and self._binary_value(start_arc[(vehicle_id, trip_id)])
            ]
            if not start_trip_ids:
                start_trip_ids = [
                    trip_id for trip_id in assigned_trip_ids if trip_id not in predecessor_by_trip
                ]
            start_trip_ids = sorted(
                set(start_trip_ids),
                key=lambda trip_id: (
                    trip_by_id[trip_id].departure_min,
                    trip_by_id[trip_id].arrival_min,
                    trip_id,
                ),
            )

            visited: Set[str] = set()
            fragments: List[List[str]] = []

            for start_trip_id in start_trip_ids:
                fragment = self._walk_vehicle_fragment(
                    start_trip_id,
                    successor_by_trip,
                    visited,
                )
                if fragment:
                    fragments.append(fragment)

            orphan_trip_ids = sorted(
                assigned_trip_ids - visited,
                key=lambda trip_id: (
                    trip_by_id[trip_id].departure_min,
                    trip_by_id[trip_id].arrival_min,
                    trip_id,
                ),
            )
            for orphan_trip_id in orphan_trip_ids:
                fragment = self._walk_vehicle_fragment(
                    orphan_trip_id,
                    successor_by_trip,
                    visited,
                )
                if fragment:
                    fragments.append(fragment)

            for fragment_index, trip_chain in enumerate(fragments, start=1):
                duty_id = f"milp_{vehicle_id}" if fragment_index == 1 else f"milp_{vehicle_id}__frag{fragment_index}"
                duty = self._vehicle_duty_from_trip_chain(
                    duty_id=duty_id,
                    vehicle_id=vehicle_id,
                    vehicle_type=str(vehicle.vehicle_type),
                    trip_chain=trip_chain,
                    dispatch_trip_by_id=dispatch_trip_by_id,
                    problem=problem,
                )
                if duty is None:
                    continue
                duties.append(duty)
                duty_vehicle_map[duty_id] = vehicle_id
                served_trip_ids.extend(trip_chain)

        return duties, served_trip_ids, duty_vehicle_map

    def _walk_vehicle_fragment(
        self,
        start_trip_id: str,
        successor_by_trip: Dict[str, str],
        visited: Set[str],
    ) -> List[str]:
        fragment: List[str] = []
        current_trip_id = str(start_trip_id)
        while current_trip_id and current_trip_id not in visited:
            visited.add(current_trip_id)
            fragment.append(current_trip_id)
            next_trip_id = successor_by_trip.get(current_trip_id)
            if not next_trip_id or next_trip_id in visited:
                break
            current_trip_id = next_trip_id
        return fragment

    def _vehicle_duty_from_trip_chain(
        self,
        *,
        duty_id: str,
        vehicle_id: str,
        vehicle_type: str,
        trip_chain: List[str],
        dispatch_trip_by_id: Dict[str, Any],
        problem: CanonicalOptimizationProblem,
    ) -> VehicleDuty | None:
        legs: List[DutyLeg] = []
        prev_trip = None
        vehicle = next(
            (item for item in problem.vehicles if str(item.vehicle_id) == str(vehicle_id)),
            None,
        )
        for trip_id in trip_chain:
            dispatch_trip = dispatch_trip_by_id.get(trip_id)
            if dispatch_trip is None:
                continue
            deadhead = 0
            if prev_trip is not None:
                deadhead = problem.dispatch_context.get_deadhead_min(
                    getattr(prev_trip, "destination_stop_id", None) or prev_trip.destination,
                    getattr(dispatch_trip, "origin_stop_id", None) or dispatch_trip.origin,
                )
            elif vehicle is not None:
                deadhead = problem.dispatch_context.get_deadhead_min(
                    str(getattr(vehicle, "home_depot_id", "") or ""),
                    getattr(dispatch_trip, "origin_stop_id", None) or dispatch_trip.origin,
                )
            legs.append(DutyLeg(trip=dispatch_trip, deadhead_from_prev_min=deadhead))
            prev_trip = dispatch_trip
        if not legs:
            return None
        return VehicleDuty(
            duty_id=duty_id,
            vehicle_type=vehicle_type,
            legs=tuple(legs),
        )

    def _vehicle_can_start_trip(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        trip: ProblemTrip | None,
    ) -> bool:
        if vehicle is None or trip is None:
            return False
        home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
        if not home_depot_id:
            return False
        dispatch_trip = problem.dispatch_context.trips_by_id().get(trip.trip_id)
        startup_trip = dispatch_trip if dispatch_trip is not None else trip
        startup_result = evaluate_startup_feasibility(
            startup_trip,
            problem.dispatch_context,
            home_depot_id,
        )
        return bool(startup_result.feasible)

    def _binary_value(self, var: Any) -> bool:
        try:
            return float(var.X) > 0.5
        except Exception:
            return False

    def _horizon_start_min(self, problem: CanonicalOptimizationProblem) -> int:
        if not problem.scenario.horizon_start:
            return 0
        try:
            hh, mm = str(problem.scenario.horizon_start).split(":")
            return int(hh) * 60 + int(mm)
        except ValueError:
            return 0

    def _trip_event_slot_index(
        self,
        problem: CanonicalOptimizationProblem,
        departure_min: int,
        arrival_min: int,
    ) -> int:
        adjusted_arrival = max(arrival_min - 1, departure_min)
        return self._slot_index(problem, adjusted_arrival)

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

    def _trip_slot_energy_fraction(
        self,
        problem: CanonicalOptimizationProblem,
        departure_min: int,
        arrival_min: int,
        slot_idx: int,
    ) -> float:
        """
        Compute the fraction of trip energy to attribute to the given slot.
        
        For mid-trip SOC safety, we spread trip energy proportionally across
        the slots where the trip is active, rather than concentrating it at
        the trip-end slot.
        
        This prevents hidden mid-trip SOC violations where a vehicle appears
        safe at trip-end but actually goes below minimum SOC mid-trip.
        """
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
        
        # No overlap with this slot
        if dep >= slot_end or arr <= slot_start:
            return 0.0
        
        trip_duration = max(arr - dep, 1)
        overlap_start = max(dep, slot_start)
        overlap_end = min(arr, slot_end)
        overlap_duration = max(overlap_end - overlap_start, 0)
        
        return overlap_duration / trip_duration

    def _build_trip_overlap_cliques(
        self,
        problem: CanonicalOptimizationProblem,
    ) -> Tuple[Tuple[str, ...], ...]:
        trip_bounds = {
            trip.trip_id: self._trip_interval_bounds(trip)
            for trip in problem.trips
        }
        departure_points = sorted({bounds[0] for bounds in trip_bounds.values()})
        candidate_cliques: List[frozenset[str]] = []
        for departure_min in departure_points:
            active_trip_ids = frozenset(
                trip_id
                for trip_id, (dep_min, arr_min) in trip_bounds.items()
                if dep_min <= departure_min < arr_min
            )
            if len(active_trip_ids) > 1:
                candidate_cliques.append(active_trip_ids)

        unique_cliques = sorted(
            set(candidate_cliques),
            key=lambda item: (-len(item), tuple(sorted(item))),
        )
        maximal_cliques: List[frozenset[str]] = []
        for clique in unique_cliques:
            if any(clique < kept for kept in maximal_cliques):
                continue
            maximal_cliques.append(clique)

        return tuple(
            tuple(
                sorted(
                    clique,
                    key=lambda trip_id: (
                        trip_bounds[trip_id][0],
                        trip_bounds[trip_id][1],
                        trip_id,
                    ),
                )
            )
            for clique in maximal_cliques
        )

    def _trip_interval_bounds(
        self,
        trip: ProblemTrip,
    ) -> Tuple[int, int]:
        departure_min = int(trip.departure_min)
        arrival_min = int(trip.arrival_min)
        if arrival_min <= departure_min:
            arrival_min += 24 * 60
        return departure_min, arrival_min

    def _trip_active_slot_count(
        self,
        problem: CanonicalOptimizationProblem,
        departure_min: int,
        arrival_min: int,
        slot_indices: List[int],
    ) -> int:
        """Count how many slots a trip is active in."""
        count = 0
        for slot_idx in slot_indices:
            if self._trip_active_in_slot(problem, departure_min, arrival_min, slot_idx):
                count += 1
        return max(count, 1)

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
        vehicle: Any,
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
        vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle.vehicle_type), None)
        if vt and vt.powertrain_type.upper() in {"BEV", "PHEV", "FCEV"}:
            drive_rate = self._vehicle_energy_rate_kwh_per_km(problem, vehicle, from_trip)
            return deadhead_km * drive_rate
        return 0.0

    def _trip_energy_kwh(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        trip_id: str,
    ) -> float:
        trip = problem.trip_by_id().get(trip_id)
        if trip is None:
            return 0.0
        drive_rate = self._vehicle_energy_rate_kwh_per_km(problem, vehicle, trip)
        if drive_rate > 0.0:
            return max(float(trip.distance_km or 0.0), 0.0) * drive_rate
        return max(float(trip.energy_kwh or 0.0), 0.0)

    def _vehicle_energy_rate_kwh_per_km(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        fallback_trip: ProblemTrip,
    ) -> float:
        vehicle_rate = max(float(getattr(vehicle, "energy_consumption_kwh_per_km", 0.0) or 0.0), 0.0)
        if vehicle_rate > 0.0:
            return vehicle_rate
        vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle.vehicle_type), None)
        if vt is not None:
            vt_rate = max(float(getattr(vt, "energy_consumption_kwh_per_km", 0.0) or 0.0), 0.0)
            if vt_rate > 0.0:
                return vt_rate
        return max(float(fallback_trip.energy_kwh or 0.0), 0.0) / max(float(fallback_trip.distance_km or 0.0), 1e-6)

    def _trip_fuel_l(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        trip_id: str,
    ) -> float:
        trip = problem.trip_by_id().get(trip_id)
        if trip is None:
            return 0.0
        fuel_rate = max(float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0)
        if fuel_rate > 0.0:
            return max(float(trip.distance_km or 0.0), 0.0) * fuel_rate
        return max(float(trip.fuel_l or 0.0), 0.0)

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

    def _soft_charge_concurrency_limit(self, port_limit: float, ratio: float) -> int:
        ports = max(int(round(float(port_limit or 0.0))), 1)
        r = min(max(float(ratio or 0.0), 0.0), 1.0)
        return max(1, min(ports, int(round(ports * r))))

    def _early_charge_weight(self, slot_idx: int, slot_indices: List[int]) -> float:
        if not slot_indices:
            return 0.0
        ordered = sorted(int(v) for v in slot_indices)
        first = ordered[0]
        last = ordered[-1]
        if last <= first:
            return 0.0
        position = min(max(int(slot_idx), first), last)
        return float(last - position) / float(last - first)

    def _route_band_key(self, dispatch_trip: Any, fallback_route_id: str) -> str:
        family_code = str(getattr(dispatch_trip, "route_family_code", "") or "").strip()
        trip_route_id = str(getattr(dispatch_trip, "route_id", "") or "").strip()
        # Fixed-route mode is family-level: collapse main/short-turn/depot variants.
        series_code, _prefix, _number, _source = extract_route_series_from_candidates(
            family_code,
            trip_route_id,
            str(fallback_route_id or "").strip(),
        )
        if series_code:
            return series_code
        if family_code:
            return family_code
        if trip_route_id:
            return trip_route_id
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

    def _required_departure_soc_kwh(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        trip: ProblemTrip,
        *,
        cap_kwh: float,
        final_soc_floor_kwh: float,
    ) -> float:
        # Vehicle-specific readiness uses trip energy + terminal floor reserve.
        # Keep required_soc_departure_percent as a backward-compatible lower bound.
        trip_energy_kwh = self._trip_energy_kwh(problem, vehicle, trip.trip_id)
        required_kwh = trip_energy_kwh + max(float(final_soc_floor_kwh or 0.0), 0.0)
        required_ratio = normalize_required_soc_departure_ratio(
            trip.required_soc_departure_percent,
            treat_values_le_one_as_percent=(
                str((problem.metadata or {}).get("required_soc_departure_unit") or "").strip().lower()
                == "percent_0_100"
            ),
        )
        if required_ratio is not None and required_ratio > 0.0 and cap_kwh > 0.0:
            required_kwh = max(required_kwh, required_ratio * cap_kwh)
        return max(required_kwh, 0.0)

