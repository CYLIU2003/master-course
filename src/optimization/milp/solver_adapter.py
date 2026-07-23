from __future__ import annotations

import csv
import hashlib
import json
import math
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Set, Tuple

from src.dispatch.feasibility import evaluate_startup_feasibility
from src.dispatch.models import DutyLeg, VehicleDuty
from src.dispatch.route_band import fragment_transition_diagnostic
from src.gurobi_runtime import ensure_gurobi, is_gurobi_available
from src.objective_modes import normalize_objective_mode
from src.optimization.common.cost_components import normalize_cost_component_flags
from src.optimization.common.bess_terminal_policy import (
    resolve_bess_terminal_soc_target_kwh,
)
from src.optimization.common.bev_terminal_policy import (
    BevTerminalSocPolicy,
    normalize_bev_terminal_soc_policy,
)
from src.optimization.milp.model_builder import MILPModelBuilder
from src.optimization.common.weather_strategy import weather_assignment_objective_bias
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
    normalize_phase,
    normalize_service_coverage_mode,
    normalize_required_soc_departure_ratio,
)
from src.optimization.common.soc_helpers import (
    effective_final_soc_target_kwh,
    final_soc_floor_kwh,
    final_soc_target_enabled,
    post_return_target_slot_index,
    return_deadhead_energy_kwh,
    return_deadhead_min_to_home,
    slot_absolute_min,
    slot_index,
    slot_index_ceil,
    vehicle_initial_soc_kwh,
)


_DRIVER_PREP_TIME_MIN = 30.0
_DRIVER_WAGE_JPY_PER_H = 2000.0
_DRIVER_REGULAR_HOURS_PER_DAY = 8.0
_DRIVER_OVERTIME_FACTOR = 1.25

ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT = "remaining_day_fixed_assignment"


def _resolved_stage_time_limit_sec(
    config: OptimizationConfig,
    *,
    stage: int,
) -> int:
    """Resolve a reproducible solver budget for one Phase 3 stage.

    Existing experiments keep the historical 50/50 split when neither
    stage-specific value is supplied.  Phase 1 charging-only runs have no
    assignment MILP, so their Stage 2 receives the full request by default.
    """

    if stage not in {1, 2}:
        raise ValueError(f"stage must be 1 or 2, got {stage!r}")
    explicit = (
        getattr(config, "stage1_time_limit_sec", None)
        if stage == 1
        else getattr(config, "stage2_time_limit_sec", None)
    )
    if explicit is not None:
        return max(int(explicit), 1)
    total = max(int(getattr(config, "time_limit_sec", 0) or 0), 1)
    phase = str(getattr(config, "phase", "") or "").strip().lower()
    if stage == 2 and normalize_phase(phase) == "phase1_charging_only":
        return total
    return max(int(max(total, 2) / 2), 1)


def _best_objective_stop_from_certified_lower_bound(
    certified_lower_bound: Optional[float],
    relative_gap: float,
) -> Optional[float]:
    """Convert a nonnegative certified lower bound into an incumbent stop.

    For minimization with a nonnegative incumbent ``z`` and lower bound ``L``,
    ``(z - L) / z <= gap`` is equivalent to ``z <= L / (1 - gap)``.
    The helper deliberately rejects negative bounds and gaps of one or more,
    where this transformation is not a valid finite stopping threshold.
    """

    if certified_lower_bound is None:
        return None
    lower_bound = float(certified_lower_bound)
    gap = max(float(relative_gap), 0.0)
    if not math.isfinite(lower_bound) or lower_bound < 0.0 or gap >= 1.0:
        return None
    return lower_bound / (1.0 - gap)


def _has_exact_mip_optimality_certificate(
    solver_status: str,
    mip_gap: Optional[float],
) -> bool:
    """Return whether a MILP result supports an exact-optimality claim.

    Gurobi can report ``OPTIMAL`` once the configured relative MIP tolerance is
    met.  That is a valid solver termination, but it is not an exact global
    optimality certificate when a positive primal--dual gap remains.  Keep the
    raw solver status separately and require a numerically zero gap for claims
    labelled "global optimality" in research artifacts.
    """

    if str(solver_status) != "optimal":
        return False
    return mip_gap is not None and float(mip_gap) <= 1.0e-8


def _single_path_flow_implies_temporal_exclusivity(
    *,
    max_start_fragments_per_vehicle: int,
    max_end_fragments_per_vehicle: int,
    arc_pairs: Sequence[Tuple[str, str, str]],
    trip_by_id: Mapping[str, ProblemTrip],
) -> bool:
    """Return whether node flow alone forces one time-ordered vehicle path."""

    if (
        int(max_start_fragments_per_vehicle) > 1
        or int(max_end_fragments_per_vehicle) > 1
    ):
        return False
    for _vehicle_id, from_trip_id, to_trip_id in arc_pairs:
        from_trip = trip_by_id.get(str(from_trip_id))
        to_trip = trip_by_id.get(str(to_trip_id))
        if from_trip is None or to_trip is None:
            return False
        if int(to_trip.departure_min) <= int(from_trip.departure_min):
            return False
    return True


def _stage2_slot_indices(
    problem: CanonicalOptimizationProblem,
    config: OptimizationConfig,
    all_slot_indices: Sequence[int],
) -> Tuple[int, ...]:
    """Return the full day or the remaining-day rolling look-ahead slots."""

    ordered = tuple(sorted({int(item) for item in all_slot_indices}))
    policy = str(getattr(config, "rolling_horizon_policy", "") or "").strip().lower()
    if policy != ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT:
        return ordered
    current_min = getattr(config, "rolling_current_min", None)
    if current_min is None:
        raise ValueError("rolling_current_min is required for remaining-day re-optimization")
    start_slot = slot_index(problem, int(current_min))
    return tuple(item for item in ordered if item >= start_slot)


def _pv_generation_kwh_at_slot(asset: DepotEnergyAsset, slot_idx: int) -> float:
    """Read PV by absolute slot index, including a rolling subset of the day."""

    values = tuple(getattr(asset, "pv_generation_kwh_by_slot", ()) or ())
    if not bool(getattr(asset, "pv_enabled", False)) or slot_idx < 0 or slot_idx >= len(values):
        return 0.0
    return max(float(values[slot_idx] or 0.0), 0.0)


def _bess_soc_max_kwh(asset: DepotEnergyAsset) -> float:
    capacity = max(float(getattr(asset, "bess_energy_kwh", 0.0) or 0.0), 0.0)
    configured_max = max(float(getattr(asset, "bess_soc_max_kwh", 0.0) or 0.0), 0.0)
    if configured_max > 0.0:
        return min(configured_max, capacity) if capacity > 0.0 else configured_max
    return capacity


def _bess_terminal_soc_target_kwh(asset: DepotEnergyAsset, *, terminal_soc_floor: float) -> Optional[float]:
    return resolve_bess_terminal_soc_target_kwh(
        policy=getattr(asset, "bess_terminal_soc_policy", ""),
        initial_soc_kwh=float(getattr(asset, "bess_initial_soc_kwh", 0.0) or 0.0),
        configured_target_kwh=float(
            getattr(asset, "bess_terminal_soc_target_kwh", 0.0) or 0.0
        ),
        terminal_soc_floor_kwh=terminal_soc_floor,
        maximum_soc_kwh=_bess_soc_max_kwh(asset),
    )


def _vehicle_soc_transition_kwh(
    slot_start_soc_kwh: Any,
    *,
    charge_power_kw: Any,
    timestep_h: float,
    charge_efficiency: float,
    drive_energy_kwh: float,
) -> Any:
    """Apply the slot-start SOC balance used by the Phase 3 MILP."""
    return (
        slot_start_soc_kwh
        + charge_efficiency * charge_power_kw * timestep_h
        - drive_energy_kwh
    )


def _remaining_posted_transition_fraction(
    *,
    event_end_min: int,
    rolling_start_abs_min: int,
) -> float:
    """Return the remaining share of a discretely posted movement event.

    Stage 2 posts startup, connection, and return deadhead energy as one event
    in the slot where the movement finishes. The SOC handed to the next hourly
    solve is a slot-boundary state from that same discrete model. Therefore an
    event finishing after the boundary has not been deducted at all and must
    remain whole; prorating it would silently lose its pre-boundary share.
    """

    return 0.0 if int(event_end_min) <= int(rolling_start_abs_min) else 1.0


def _transition_slot_ending_at_event(
    slot_indices: Sequence[int],
    event_slot: int,
) -> Optional[int]:
    """Return the SOC transition whose end state is ``event_slot``.

    A return deadhead completed at the start of ``event_slot`` must reduce the
    preceding transition. Posting it to ``event_slot`` would let same-slot
    charging mask a below-reserve post-return state.
    """
    ordered = tuple(sorted({int(slot_idx) for slot_idx in slot_indices}))
    try:
        position = ordered.index(int(event_slot))
    except ValueError:
        return None
    return ordered[position - 1] if position > 0 else None


def _supports_full_candidate_network_exact_milp(
    arc_pruning_summary: Mapping[str, Any],
) -> bool:
    """Return whether the MILP retained the complete feasible arc network.

    Gurobi can solve the constructed model exactly while that model is still a
    successor-pruned approximation of the original candidate network.  The
    public ``supports_exact_milp`` flag describes the latter, stronger claim.
    """

    if "pruned_arc_count" not in arc_pruning_summary:
        return False
    try:
        pruned_arc_count = int(arc_pruning_summary.get("pruned_arc_count") or 0)
    except (TypeError, ValueError):
        return False
    return pruned_arc_count == 0


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


@dataclass(frozen=True)
class StartupEnergyPrecheck:
    """Optimistic necessary condition for assigning a vehicle's first trip."""

    path_feasible: bool
    energy_feasible: bool
    initial_soc_kwh: float
    minimum_soc_kwh: float
    startup_deadhead_min: int
    startup_deadhead_energy_kwh: float
    required_departure_soc_kwh: float
    complete_precharge_slot_count: int
    maximum_precharge_energy_kwh: float
    energy_margin_kwh: float


@dataclass(frozen=True)
class Stage1EnergyCostProxy:
    """Aggregate source-energy lower bound used by Phase 3 Stage 1.

    The proxy connects assignment-dependent BEV energy need to the configured
    PV, stationary-battery, and grid marginal costs without pretending that
    Stage 1 contains the time-indexed charging dispatch solved by Stage 2.
    """

    objective_expression: Any
    external_charge_input_by_vehicle: Mapping[str, Any]
    net_battery_requirement_by_vehicle: Mapping[str, Any]
    home_depot_by_vehicle: Mapping[str, str]
    pv_to_bus_by_depot: Mapping[str, Any]
    grid_to_bus_by_depot: Mapping[str, Any]
    bess_initial_to_bus_by_depot: Mapping[str, Any]
    configuration: Mapping[str, Any]
    weather_input: Mapping[str, Any]


@dataclass
class _Stage1SearchTelemetry:
    """Compact, read-only telemetry for diagnosing Stage 1 MIP search.

    The collector never terminates the solver or changes parameters.  Periodic
    progress is sampled to keep callback overhead and artifact size bounded;
    every incumbent notification is counted, while only a bounded number of
    events is retained.
    """

    requested_gap_ratio: float
    sample_interval_sec: float = 5.0
    max_incumbent_events: int = 200
    progress_samples: List[Dict[str, Any]] = field(default_factory=list)
    incumbent_events: List[Dict[str, Any]] = field(default_factory=list)
    first_incumbent_runtime_sec: Optional[float] = None
    requested_gap_reached_runtime_sec: Optional[float] = None
    incumbent_notification_count: int = 0
    dropped_incumbent_event_count: int = 0
    callback_error: str = ""
    _last_progress_runtime_sec: Optional[float] = field(
        default=None,
        init=False,
        repr=False,
    )

    @staticmethod
    def _finite_or_none(value: Any) -> Optional[float]:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        # Gurobi represents a missing incumbent/bound with a large finite
        # sentinel (normally 1e100), which must not be mistaken for gap zero.
        return result if math.isfinite(result) and abs(result) < 1.0e90 else None

    @classmethod
    def _relative_gap(
        cls,
        incumbent_objective: Any,
        best_bound: Any,
    ) -> Optional[float]:
        incumbent = cls._finite_or_none(incumbent_objective)
        bound = cls._finite_or_none(best_bound)
        if incumbent is None or bound is None:
            return None
        return max(incumbent - bound, 0.0) / max(abs(incumbent), 1.0e-9)

    def _event(
        self,
        *,
        runtime_sec: Any,
        incumbent_objective: Any,
        best_bound: Any,
        explored_node_count: Any,
        solution_count: Any,
    ) -> Dict[str, Any]:
        incumbent = self._finite_or_none(incumbent_objective)
        bound = self._finite_or_none(best_bound)
        nodes = self._finite_or_none(explored_node_count)
        solutions = self._finite_or_none(solution_count)
        return {
            "runtime_sec": self._finite_or_none(runtime_sec),
            "incumbent_objective": incumbent,
            "best_bound": bound,
            "relative_gap_ratio": self._relative_gap(incumbent, bound),
            "explored_node_count": int(nodes) if nodes is not None else None,
            "solution_count": int(solutions) if solutions is not None else None,
        }

    def _record_requested_gap_time(self, event: Mapping[str, Any]) -> None:
        gap = event.get("relative_gap_ratio")
        runtime_sec = event.get("runtime_sec")
        if (
            self.requested_gap_reached_runtime_sec is None
            and gap is not None
            and float(gap) <= max(float(self.requested_gap_ratio), 0.0) + 1.0e-12
            and runtime_sec is not None
        ):
            self.requested_gap_reached_runtime_sec = float(runtime_sec)

    def record_progress(
        self,
        *,
        runtime_sec: Any,
        incumbent_objective: Any,
        best_bound: Any,
        explored_node_count: Any,
        solution_count: Any,
        force: bool = False,
    ) -> None:
        runtime = self._finite_or_none(runtime_sec)
        if runtime is None:
            return
        if (
            not force
            and self._last_progress_runtime_sec is not None
            and runtime - self._last_progress_runtime_sec < self.sample_interval_sec
        ):
            return
        event = self._event(
            runtime_sec=runtime,
            incumbent_objective=incumbent_objective,
            best_bound=best_bound,
            explored_node_count=explored_node_count,
            solution_count=solution_count,
        )
        self.progress_samples.append(event)
        self._last_progress_runtime_sec = runtime
        self._record_requested_gap_time(event)

    def record_incumbent(
        self,
        *,
        runtime_sec: Any,
        incumbent_objective: Any,
        best_bound: Any,
        explored_node_count: Any,
        solution_count: Any,
    ) -> None:
        event = self._event(
            runtime_sec=runtime_sec,
            incumbent_objective=incumbent_objective,
            best_bound=best_bound,
            explored_node_count=explored_node_count,
            solution_count=solution_count,
        )
        self.incumbent_notification_count += 1
        runtime = event.get("runtime_sec")
        if self.first_incumbent_runtime_sec is None and runtime is not None:
            self.first_incumbent_runtime_sec = float(runtime)
        if len(self.incumbent_events) < max(int(self.max_incumbent_events), 0):
            self.incumbent_events.append(event)
        else:
            self.dropped_incumbent_event_count += 1
        self._record_requested_gap_time(event)

    def to_dict(
        self,
        *,
        final_runtime_sec: Any,
        final_incumbent_objective: Any,
        final_best_bound: Any,
        final_node_count: Any,
        final_solution_count: Any,
        final_simplex_iteration_count: Any,
        final_barrier_iteration_count: Any,
    ) -> Dict[str, Any]:
        final_event = self._event(
            runtime_sec=final_runtime_sec,
            incumbent_objective=final_incumbent_objective,
            best_bound=final_best_bound,
            explored_node_count=final_node_count,
            solution_count=final_solution_count,
        )
        self._record_requested_gap_time(final_event)
        return {
            "schema_version": "stage1_search_telemetry_v1",
            "sample_interval_sec": float(self.sample_interval_sec),
            "requested_gap_ratio": max(float(self.requested_gap_ratio), 0.0),
            "first_incumbent_runtime_sec": self.first_incumbent_runtime_sec,
            "requested_gap_reached_runtime_sec": (
                self.requested_gap_reached_runtime_sec
            ),
            "incumbent_notification_count": int(
                self.incumbent_notification_count
            ),
            "retained_incumbent_event_count": len(self.incumbent_events),
            "dropped_incumbent_event_count": int(
                self.dropped_incumbent_event_count
            ),
            "progress_sample_count": len(self.progress_samples),
            "progress_samples": list(self.progress_samples),
            "incumbent_events": list(self.incumbent_events),
            "final": final_event,
            "final_simplex_iteration_count": self._finite_or_none(
                final_simplex_iteration_count
            ),
            "final_barrier_iteration_count": self._finite_or_none(
                final_barrier_iteration_count
            ),
            "callback_error": self.callback_error or None,
        }


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
                solver_status="BASELINE_FALLBACK" if has_feasible_incumbent else "baseline_infeasible_strict",
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
        raw_phase = str(getattr(config, "phase", "") or "").strip()
        phase = normalize_phase(raw_phase) if raw_phase else ""

        if phase == "phase1_charging_only":
            return self._solve_charging_only(problem, config)
        if phase == "phase2_assignment_only":
            return self._solve_assignment_only(problem, config)
        if phase == "diagnostic":
            return self._solve_diagnostic(problem, config)

        if phase == "phase4_integrated":
            # Fall through to the inline integrated MILP build below.
            pass
        elif bool(getattr(config, "thesis_mode", False)) or phase == "phase3_two_stage":
            return self._solve_thesis_two_stage(problem, config)
        if not is_gurobi_available():
            if bool(getattr(config, "research_run", False)):
                return (
                    MILPSolverOutcome(
                        solver_status="NO_VALID_INCUMBENT",
                        used_backend="none",
                        supports_exact_milp=False,
                        fallback_reason="gurobi_unavailable",
                    ),
                    AssignmentPlan(
                        duties=(),
                        served_trip_ids=(),
                        unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips)),
                        metadata={
                            "source": "milp_gurobi",
                            "status": "NO_VALID_INCUMBENT",
                            "research_run": True,
                            "research_kpi_eligible": False,
                        },
                    ),
                )
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
        arc_pruning_summary = builder.arc_pruning_summary(problem, trip_by_id)
        vehicle_by_id = {
            str(vehicle.vehicle_id): vehicle
            for vehicle in problem.vehicles
        }
        vehicle_type_by_id = {str(item.vehicle_type_id): item for item in problem.vehicle_types}
        assignment_trip_ids_by_vehicle: Dict[str, List[str]] = {}
        assignment_vehicle_ids_by_trip: Dict[str, List[str]] = {}
        startup_feasible_by_assignment: Dict[Tuple[str, str], bool] = {}
        startup_energy_precheck_by_assignment: Dict[
            Tuple[str, str], StartupEnergyPrecheck
        ] = {}
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
            startup_energy_precheck_by_assignment[(vehicle_id, trip_id)] = (
                self._startup_energy_precheck(
                    problem,
                    vehicle_by_id.get(str(vehicle_id)),
                    trip_by_id.get(str(trip_id)),
                    dispatch_trip_by_id=dispatch_trip_by_id,
                )
            )
            if not startup_feasible_by_assignment[(vehicle_id, trip_id)]:
                startup_infeasible_trip_ids.add(str(trip_id))
                startup_infeasible_vehicle_ids.add(str(vehicle_id))
        fixed_route_band_mode = bool(problem.metadata.get("fixed_route_band_mode", False))
        service_coverage_mode = normalize_service_coverage_mode(
            getattr(problem.scenario, "service_coverage_mode", None)
            or problem.metadata.get("service_coverage_mode", "strict")
        )
        allow_partial_service = service_coverage_mode == "penalized" or bool(
            getattr(config, "debug_mode", False)
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
        final_target_enabled = final_soc_target_enabled(problem)
        if final_target_enabled:
            for (vehicle_id, trip_id), var in end_arc.items():
                vehicle = vehicle_by_id.get(str(vehicle_id))
                trip = trip_by_id.get(str(trip_id))
                if vehicle is None or trip is None:
                    continue
                if str(getattr(vehicle, "vehicle_type", "") or "").upper() not in {"BEV", "PHEV", "FCEV"}:
                    continue
                return_exists, _return_deadhead_min = return_deadhead_min_to_home(
                    problem,
                    vehicle,
                    trip,
                )
                if not return_exists:
                    model.addConstr(var == 0)

        # Strict research runs represent coverage directly as assignment
        # equality.  Do not create fixed-zero ``unserved`` variables: they
        # obscure the mathematical contract and bloat the integrated model.
        unserved: Dict[str, Any] = (
            {
                trip.trip_id: model.addVar(vtype=GRB.BINARY)
                for trip in problem.trips
            }
            if allow_partial_service
            else {}
        )

        used_vehicle: Dict[str, Any] = {
            vehicle.vehicle_id: model.addVar(vtype=GRB.BINARY)
            for vehicle in problem.vehicles
        }
        planning_days = max(int(problem.metadata.get("planning_days") or problem.scenario.planning_days or 1), 1)
        slots_per_day = max(1, (24 * 60) // max(problem.scenario.timestep_min, 1))
        day_indices = sorted(set(range(planning_days)) | set(trip_day_index_by_trip_id.values()))
        used_vehicle_day: Dict[Tuple[str, int], Any] = {
            (vehicle.vehicle_id, day_idx): model.addVar(vtype=GRB.BINARY)
            for vehicle in problem.vehicles
            for day_idx in day_indices
        }
        integrated_strict_precheck = dict(
            problem.metadata.get("strict_coverage_precheck") or {}
        )
        integrated_vehicle_count_lower_bound = max(
            int(integrated_strict_precheck.get("relaxed_vehicle_lower_bound") or 0),
            0,
        )
        if integrated_vehicle_count_lower_bound > 0:
            model.addConstr(
                gp.quicksum(used_vehicle_day.values())
                >= integrated_vehicle_count_lower_bound,
                name="integrated_strict_path_cover_vehicle_day_lb",
            )

        assignment_day_indices_by_vehicle: Dict[str, Set[int]] = {}
        for vehicle_id, trip_ids in assignment_trip_ids_by_vehicle.items():
            for trip_id in trip_ids:
                assignment_day_indices_by_vehicle.setdefault(vehicle_id, set()).add(
                    int(trip_day_index_by_trip_id.get(trip_id, 0))
                )

        upper_buffer_ratio = self._percent_to_ratio(problem.metadata.get("charge_upper_buffer_ratio"))
        if upper_buffer_ratio is None:
            upper_buffer_ratio = 0.9
        buffer_topup_enabled = upper_buffer_ratio > 0.0

        # Strict coverage is a hard equality; diagnostics may relax it with an
        # explicit unserved decision variable.
        for trip in problem.trips:
            assign_terms = [y[(vehicle_id, trip.trip_id)] for vehicle_id in assignment_vehicle_ids_by_trip.get(trip.trip_id, [])]
            if allow_partial_service:
                model.addConstr(gp.quicksum(assign_terms) + unserved[trip.trip_id] == 1)
            else:
                model.addConstr(gp.quicksum(assign_terms) == 1)

        # Vehicle-use linkage.
        for (vehicle_id, trip_id), var in y.items():
            model.addConstr(var <= used_vehicle[vehicle_id])
        for vehicle in problem.vehicles:
            if not bool(getattr(vehicle, "available", True)):
                model.addConstr(used_vehicle[vehicle.vehicle_id] == 0)
        minimum_used_bev_count = max(
            int(problem.metadata.get("minimum_used_bev_count") or 0),
            0,
        )
        available_bev_use_vars = [
            used_vehicle[vehicle.vehicle_id]
            for vehicle in problem.vehicles
            if bool(getattr(vehicle, "available", True))
            and str(getattr(vehicle, "vehicle_type", "") or "").upper() == "BEV"
        ]
        if minimum_used_bev_count > len(available_bev_use_vars):
            raise ValueError(
                "minimum_used_bev_count exceeds available BEV inventory: "
                f"{minimum_used_bev_count} > {len(available_bev_use_vars)}"
            )
        if minimum_used_bev_count > 0:
            model.addConstr(
                gp.quicksum(available_bev_use_vars) >= minimum_used_bev_count,
                name="minimum_used_bev_count_policy",
            )

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
            model.addConstr(
                used_vehicle[vehicle_id]
                <= gp.quicksum(
                    used_vehicle_day[(vehicle_id, day_idx)]
                    for day_idx in day_indices
                )
            )

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

        integrated_single_path_redundancy_elimination_applied = (
            _single_path_flow_implies_temporal_exclusivity(
                max_start_fragments_per_vehicle=max_start_fragments_per_vehicle,
                max_end_fragments_per_vehicle=max_end_fragments_per_vehicle,
                arc_pairs=arc_pairs,
                trip_by_id=trip_by_id,
            )
        )
        integrated_fragment_pairwise_constraint_count = 0
        integrated_fragment_occupancy_constraint_count = 0
        if not integrated_single_path_redundancy_elimination_applied:
            integrated_fragment_pairwise_constraint_count = (
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
            )
            integrated_fragment_occupancy_constraint_count = (
                self._add_fragment_temporal_occupancy_constraints(
                    model,
                    grb=GRB,
                    trip_by_id=trip_by_id,
                    vehicles=problem.vehicles,
                    assignment_trip_ids_by_vehicle=assignment_trip_ids_by_vehicle,
                    start_arc=start_arc,
                    end_arc=end_arc,
                    problem=problem,
                )
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
        integrated_overlap_clique_constraint_count = 0
        if overlap_cliques and not integrated_single_path_redundancy_elimination_applied:
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
                    integrated_overlap_clique_constraint_count += 1

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
        electric_startup_deadhead_kwh_by_slot: Dict[
            int, List[Tuple[float, Tuple[str, str]]]
        ] = {slot_idx: [] for slot_idx in slot_indices}
        electric_return_deadhead_kwh_by_slot: Dict[int, List[Tuple[float, Tuple[str, str]]]] = {
            slot_idx: [] for slot_idx in slot_indices
        }
        electric_terminal_return_kwh_by_vehicle_day: Dict[
            Tuple[str, int], List[Tuple[float, Tuple[str, str]]]
        ] = {}
        for vehicle in problem.vehicles:
            if vehicle.vehicle_id not in electric_vehicle_ids:
                continue
            for trip in problem.trips:
                key = (vehicle.vehicle_id, trip.trip_id)
                if key not in y:
                    continue
                startup_precheck = startup_energy_precheck_by_assignment.get(key)
                if (
                    startup_precheck is not None
                    and startup_precheck.startup_deadhead_energy_kwh > 0.0
                ):
                    departure_slot_idx = self._slot_index(
                        problem, trip.departure_min
                    )
                    electric_startup_deadhead_kwh_by_slot.setdefault(
                        departure_slot_idx, []
                    ).append(
                        (
                            float(startup_precheck.startup_deadhead_energy_kwh),
                            key,
                        )
                    )
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
            if final_target_enabled:
                for trip in problem.trips:
                    end_key = (vehicle.vehicle_id, trip.trip_id)
                    if end_key not in end_arc:
                        continue
                    return_exists, return_deadhead_min = return_deadhead_min_to_home(
                        problem,
                        vehicle,
                        trip,
                    )
                    if not return_exists:
                        continue
                    return_kwh = return_deadhead_energy_kwh(problem, vehicle, trip)
                    if return_kwh <= 0.0:
                        continue
                    return_complete_min = self._trip_service_arrival_min(problem, trip) + int(
                        return_deadhead_min
                    )
                    return_event_slot = slot_index_ceil(problem, return_complete_min)
                    transition_slot = _transition_slot_ending_at_event(
                        slot_indices,
                        return_event_slot,
                    )
                    if transition_slot is None:
                        day_idx = int(
                            trip_day_index_by_trip_id.get(trip.trip_id, 0)
                        )
                        electric_terminal_return_kwh_by_vehicle_day.setdefault(
                            (vehicle.vehicle_id, day_idx), []
                        ).append((return_kwh, end_key))
                    else:
                        electric_return_deadhead_kwh_by_slot.setdefault(
                            transition_slot, []
                        ).append((return_kwh, end_key))

        ice_startup_fuel_l_by_assignment: Dict[Tuple[str, str], float] = {}
        ice_return_fuel_l_by_assignment: Dict[Tuple[str, str], float] = {}
        ice_startup_fuel_l_by_slot: Dict[
            int, List[Tuple[float, Tuple[str, str]]]
        ] = {slot_idx: [] for slot_idx in slot_indices}
        ice_return_fuel_l_by_slot: Dict[
            int, List[Tuple[float, Tuple[str, str]]]
        ] = {slot_idx: [] for slot_idx in slot_indices}
        ice_terminal_return_fuel_l_by_vehicle: Dict[
            str, List[Tuple[float, Tuple[str, str]]]
        ] = {}
        for vehicle in problem.vehicles:
            if vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}:
                continue
            fuel_rate = max(
                float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0
            )
            if fuel_rate <= 0.0:
                continue
            for trip in problem.trips:
                assignment_key = (vehicle.vehicle_id, trip.trip_id)
                if assignment_key not in y:
                    continue
                startup_precheck = startup_energy_precheck_by_assignment.get(
                    assignment_key
                )
                startup_deadhead_min = int(
                    getattr(startup_precheck, "startup_deadhead_min", 0) or 0
                )
                startup_fuel_l = (
                    self._deadhead_distance_km(problem, startup_deadhead_min)
                    * fuel_rate
                )
                if startup_fuel_l > 0.0:
                    ice_startup_fuel_l_by_assignment[assignment_key] = (
                        startup_fuel_l
                    )
                    departure_slot_idx = self._slot_index(
                        problem, trip.departure_min
                    )
                    ice_startup_fuel_l_by_slot.setdefault(
                        departure_slot_idx, []
                    ).append((startup_fuel_l, assignment_key))

                return_exists, return_deadhead_min = return_deadhead_min_to_home(
                    problem,
                    vehicle,
                    trip,
                )
                if not return_exists:
                    continue
                return_fuel_l = (
                    self._deadhead_distance_km(
                        problem, int(return_deadhead_min)
                    )
                    * fuel_rate
                )
                if return_fuel_l <= 0.0:
                    continue
                ice_return_fuel_l_by_assignment[assignment_key] = return_fuel_l
                return_complete_min = self._trip_service_arrival_min(
                    problem, trip
                ) + int(return_deadhead_min)
                return_event_slot = slot_index_ceil(
                    problem, return_complete_min
                )
                transition_slot = _transition_slot_ending_at_event(
                    slot_indices,
                    return_event_slot,
                )
                if transition_slot is None:
                    ice_terminal_return_fuel_l_by_vehicle.setdefault(
                        vehicle.vehicle_id, []
                    ).append((return_fuel_l, assignment_key))
                else:
                    ice_return_fuel_l_by_slot.setdefault(
                        transition_slot, []
                    ).append((return_fuel_l, assignment_key))

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
        g2vehicle_var: Dict[Tuple[str, int], Any] = {}
        pv2vehicle_var: Dict[Tuple[str, int], Any] = {}
        bess2vehicle_var: Dict[Tuple[str, int], Any] = {}
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
        bess_terminal_soc_deviation_var: Dict[str, Any] = {}
        end_soc_excess_dev_var: Dict[str, Any] = {}
        opportunistic_topup_deficit_var: Dict[Tuple[str, int], Any] = {}
        charge_session_start_var: Dict[Tuple[str, int], Any] = {}
        soc_upper_excess_var: Dict[Tuple[str, int], Any] = {}
        soc_bound_violation_var: Dict[Tuple[str, int, str], Any] = {}
        slot_concurrency_excess_var: Dict[Tuple[str, int], Any] = {}
        charge_ports_by_depot: Dict[str, float] = {}
        physical_charger_assignment_var: Dict[Tuple[str, str, int], Any] = {}
        physical_charger_power_var: Dict[Tuple[str, str, int], Any] = {}
        physical_charger_metadata: Dict[str, Any] = {}
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
        connection_arcs_by_vehicle: Dict[str, List[Tuple[str, str, Any]]] = {}
        for (vehicle_id, from_trip_id, to_trip_id), arc_var in x.items():
            connection_arcs_by_vehicle.setdefault(str(vehicle_id), []).append(
                (str(from_trip_id), str(to_trip_id), arc_var)
            )
        away_from_home_slot_terms: Dict[Tuple[str, int], List[Any]] = {}
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
                # Match Stage 2's initial at-home assumption.  The selected
                # start arc identifies the first trip of the single daily path;
                # the vehicle may charge from the horizon start until it must
                # leave its home depot for that trip.  Slots intersecting the
                # startup deadhead are marked away from home below.
                for trip in problem.trips:
                    start_key = (vehicle_id, trip.trip_id)
                    start_var = start_arc.get(start_key)
                    if start_var is None:
                        continue
                    startup_precheck = startup_energy_precheck_by_assignment[
                        start_key
                    ]
                    first_window_start = self._horizon_start_min(problem)
                    first_departure_min = self._service_minute(
                        problem, int(trip.departure_min)
                    )
                    leave_depot_min = first_departure_min - int(
                        startup_precheck.startup_deadhead_min
                    )
                    for slot_idx in self._slot_indices_for_interval(
                        problem,
                        first_window_start,
                        max(leave_depot_min, first_window_start + 1),
                    ):
                        if first_slot_idx <= slot_idx <= last_slot_idx:
                            home_depot_slot_proxy_terms.setdefault(
                                (vehicle_id, slot_idx), []
                            ).append(start_var)
                    if startup_precheck.startup_deadhead_min > 0:
                        for slot_idx in self._slot_indices_for_interval(
                            problem,
                            leave_depot_min,
                            first_departure_min,
                        ):
                            if first_slot_idx <= slot_idx <= last_slot_idx:
                                away_from_home_slot_terms.setdefault(
                                    (vehicle_id, slot_idx), []
                                ).append(start_var)
                # Match the exact Stage 2 location logic: a selected
                # connection arc may create a confirmed at-home residence
                # interval between its two trips.  Without these terms the
                # integrated model incorrectly forbids inter-trip depot
                # charging that Phase 3 Stage 2 permits and validates.
                for from_trip_id, to_trip_id, arc_var in (
                    connection_arcs_by_vehicle.get(str(vehicle_id), [])
                ):
                    previous_trip = trip_by_id.get(str(from_trip_id))
                    next_trip = trip_by_id.get(str(to_trip_id))
                    if previous_trip is None or next_trip is None:
                        continue
                    deadhead_min = self._connection_deadhead_min(
                        problem,
                        previous_trip,
                        next_trip,
                    )
                    residence_interval = self._home_depot_residence_interval(
                        problem,
                        vehicle,
                        previous_trip,
                        next_trip,
                        deadhead_min=deadhead_min,
                    )
                    if residence_interval is not None:
                        for slot_idx in self._slot_indices_for_interval(
                            problem,
                            residence_interval[0],
                            residence_interval[1],
                        ):
                            if slot_idx < first_slot_idx or slot_idx > last_slot_idx:
                                continue
                            home_depot_slot_proxy_terms.setdefault(
                                (vehicle_id, slot_idx), []
                            ).append(arc_var)
                    if deadhead_min > 0:
                        deadhead_start_min, deadhead_end_min = (
                            self._connection_deadhead_interval(
                                problem,
                                vehicle,
                                previous_trip,
                                next_trip,
                                deadhead_min=deadhead_min,
                            )
                        )
                        for slot_idx in self._slot_indices_for_interval(
                            problem,
                            deadhead_start_min,
                            deadhead_end_min,
                        ):
                            if first_slot_idx <= slot_idx <= last_slot_idx:
                                away_from_home_slot_terms.setdefault(
                                    (vehicle_id, slot_idx), []
                                ).append(arc_var)
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
                if final_target_enabled or buffer_topup_enabled:
                    for trip in problem.trips:
                        key = (vehicle_id, trip.trip_id)
                        if key not in end_arc:
                            continue
                        return_exists, return_deadhead_min = return_deadhead_min_to_home(
                            problem,
                            vehicle,
                            trip,
                        )
                        if not return_exists:
                            continue
                        day_idx = int(trip_day_index_by_trip_id.get(trip.trip_id, 0))
                        target_slots = self._collect_post_return_target_slots(
                            problem,
                            trip=trip,
                            day_idx=day_idx,
                            return_deadhead_min=return_deadhead_min,
                        )
                        for slot_idx in target_slots:
                            if slot_idx < first_slot_idx or slot_idx > last_slot_idx:
                                continue
                            home_depot_slot_proxy_terms.setdefault((vehicle_id, slot_idx), []).append(
                                end_arc[key]
                            )

        if bev_ids and slot_indices:
            soc_violation_slack_enabled = self._metadata_truthy(
                problem.metadata.get("allow_soc_violation_slack")
                if problem.metadata.get("allow_soc_violation_slack") is not None
                else problem.metadata.get("use_soft_soc_constraint")
            )
            final_soc_floor_ratio_override = self._percent_to_ratio(problem.metadata.get("final_soc_floor_percent"))
            final_soc_target_ratio_override = self._percent_to_ratio(problem.metadata.get("final_soc_target_percent"))
            for vehicle in problem.vehicles:
                if vehicle.vehicle_id not in bev_ids:
                    continue
                vehicle_available = bool(getattr(vehicle, "available", True))
                cap = max(vehicle.battery_capacity_kwh or 300.0, 1.0)
                reserve = vehicle.reserve_soc
                if reserve is None:
                    soc_min = 0.15 * cap
                elif reserve <= 1.0:
                    soc_min = reserve * cap
                else:
                    soc_min = reserve

                charge_max_kw = self._vehicle_charge_power_max_kw(problem, vehicle)
                if problem.chargers:
                    # The physical assignment below applies the selected
                    # charger's exact limit; this is only a safe variable bound.
                    max_charger_kw = max(float(charger.power_kw or 0.0) for charger in problem.chargers)
                    if max_charger_kw > 0.0:
                        charge_max_kw = min(charge_max_kw, max_charger_kw)
                discharge_max_kw = self._discharge_power_max_kw(problem, vehicle.vehicle_type)

                for slot_idx in slot_indices:
                    charge_on_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(vtype=GRB.BINARY)
                    charge_session_start_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(vtype=GRB.BINARY)
                    c_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(lb=0.0, ub=charge_max_kw, vtype=GRB.CONTINUOUS)
                    d_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(lb=0.0, ub=discharge_max_kw, vtype=GRB.CONTINUOUS)
                    if soc_violation_slack_enabled:
                        # Diagnostic mode only: production research runs must not buy SOC violations with cost.
                        s_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(lb=0.0, ub=cap * 1.2, vtype=GRB.CONTINUOUS)
                        soc_lower_deficit = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"soc_deficit_{vehicle.vehicle_id}_{slot_idx}")
                        soc_upper_excess = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"soc_excess_{vehicle.vehicle_id}_{slot_idx}")
                        soc_bound_violation_var[(vehicle.vehicle_id, slot_idx, "lower")] = soc_lower_deficit
                        soc_bound_violation_var[(vehicle.vehicle_id, slot_idx, "upper")] = soc_upper_excess
                        model.addConstr(s_var[(vehicle.vehicle_id, slot_idx)] + soc_lower_deficit >= soc_min)
                        model.addConstr(s_var[(vehicle.vehicle_id, slot_idx)] - soc_upper_excess <= cap)
                    else:
                        s_var[(vehicle.vehicle_id, slot_idx)] = model.addVar(lb=soc_min, ub=cap, vtype=GRB.CONTINUOUS)

                # ProblemBuilder has already resolved the selected initial-SOC
                # policy into each vehicle. Re-reading the scenario-wide
                # fallback here would overwrite actual per-vehicle inventory.
                initial_kwh = vehicle_initial_soc_kwh(
                    problem,
                    vehicle,
                    cap_kwh=cap,
                )
                initial_kwh = min(max(initial_kwh, soc_min), cap)
                first_slot = slot_indices[0]
                model.addConstr(s_var[(vehicle.vehicle_id, first_slot)] == initial_kwh)

                def _slot_end_soc_expr(slot_idx: int, day_idx: int) -> Any:
                    trip_load = gp.quicksum(
                        energy_kwh * y[assignment_key]
                        for energy_kwh, assignment_key in electric_trip_kwh_by_slot.get(
                            slot_idx, []
                        )
                        if assignment_key[0] == vehicle.vehicle_id
                    )
                    startup_load = gp.quicksum(
                        energy_kwh * start_arc[start_key]
                        for energy_kwh, start_key in (
                            electric_startup_deadhead_kwh_by_slot.get(
                                slot_idx, []
                            )
                        )
                        if start_key[0] == vehicle.vehicle_id
                    )
                    connection_load = gp.quicksum(
                        energy_kwh * x[arc_key]
                        for energy_kwh, arc_key in electric_deadhead_kwh_by_slot.get(
                            slot_idx, []
                        )
                        if arc_key[0] == vehicle.vehicle_id
                    )
                    return_load = gp.quicksum(
                        energy_kwh * end_arc[end_key]
                        for energy_kwh, end_key in electric_return_deadhead_kwh_by_slot.get(
                            slot_idx, []
                        )
                        if end_key[0] == vehicle.vehicle_id
                    )
                    terminal_return_load = gp.quicksum(
                        energy_kwh * end_arc[end_key]
                        for energy_kwh, end_key in electric_terminal_return_kwh_by_vehicle_day.get(
                            (vehicle.vehicle_id, day_idx), []
                        )
                    )
                    return (
                        s_var[(vehicle.vehicle_id, slot_idx)]
                        + 0.95 * c_var[(vehicle.vehicle_id, slot_idx)] * timestep_h
                        - d_var[(vehicle.vehicle_id, slot_idx)] * timestep_h / 0.95
                        - trip_load
                        - startup_load
                        - connection_load
                        - return_load
                        - terminal_return_load
                    )

                # C11: terminal SOC lower bound.
                last_slot = slot_indices[-1]
                final_soc_floor_kwh = soc_min
                if final_soc_floor_ratio_override is not None:
                    final_soc_floor_kwh = max(final_soc_floor_kwh, final_soc_floor_ratio_override * cap)
                final_day_idx = max(day_indices) if day_indices else 0
                final_slot_end_soc = _slot_end_soc_expr(
                    last_slot,
                    final_day_idx,
                )
                model.addConstr(
                    final_slot_end_soc
                    >= final_soc_floor_kwh * used_vehicle[vehicle.vehicle_id]
                )
                model.addConstr(final_slot_end_soc <= cap)

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
                        _slot_end_soc_expr(day_slot_idx, day_idx)
                        >= final_soc_floor_kwh * day_use_var
                    )

                    if final_target_enabled:
                        target_slot_idx = post_return_target_slot_index(problem, day_idx)
                        target_soc_key = (vehicle.vehicle_id, target_slot_idx)
                        hard_target_kwh = effective_final_soc_target_kwh(
                            problem,
                            vehicle,
                            cap_kwh=cap,
                        )
                        if hard_target_kwh is not None and target_soc_key in s_var:
                            model.addConstr(
                                _slot_end_soc_expr(target_slot_idx, day_idx)
                                >= hard_target_kwh * day_use_var
                            )
                            terminal_policy = normalize_bev_terminal_soc_policy(
                                problem.metadata.get("bev_terminal_soc_policy"),
                                has_explicit_target=(
                                    problem.metadata.get("final_soc_target_percent")
                                    is not None
                                ),
                            )
                            if terminal_policy is BevTerminalSocPolicy.RETURN_TO_INITIAL:
                                tolerance_kwh = self._safe_nonnegative_float(
                                    problem.metadata.get(
                                        "bev_terminal_soc_equality_tolerance_kwh"
                                    ),
                                    default=1.0e-6,
                                )
                                model.addConstr(
                                    _slot_end_soc_expr(target_slot_idx, day_idx)
                                    <= hard_target_kwh
                                    + tolerance_kwh
                                    + cap * (1 - day_use_var)
                                )
                        continue

                if upper_buffer_ratio is not None and upper_buffer_ratio > 0.0:
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

                if buffer_topup_enabled and vehicle_available:
                    opportunistic_target_kwh = min(
                        cap,
                        max(
                            max(float(upper_buffer_ratio or 0.0), 0.0) * cap,
                            max(float(effective_final_soc_target_kwh(problem, vehicle, cap_kwh=cap) or 0.0), 0.0),
                        ),
                    )
                    for day_idx in day_indices:
                        day_soc_key = (vehicle.vehicle_id, self._day_end_slot_index(
                            problem,
                            day_idx=day_idx,
                            operation_start_min=operation_start_min,
                            operation_end_min=operation_end_min,
                        ))
                        if day_soc_key not in s_var:
                            continue
                        deficit_key = (vehicle.vehicle_id, day_idx)
                        opportunistic_topup_deficit_var[deficit_key] = model.addVar(
                            lb=0.0,
                            vtype=GRB.CONTINUOUS,
                            name=f"opportunistic_topup_deficit_{vehicle.vehicle_id}_{day_idx}",
                        )
                        model.addConstr(
                            opportunistic_topup_deficit_var[deficit_key]
                            >= opportunistic_target_kwh - s_var[day_soc_key]
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
                        + float(
                            getattr(
                                startup_energy_precheck_by_assignment.get(key),
                                "startup_deadhead_energy_kwh",
                                0.0,
                            )
                            or 0.0
                        )
                        * start_arc[key]
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
                    startup_deadhead_energy_expr = gp.quicksum(
                        energy_kwh * start_arc[start_key]
                        for energy_kwh, start_key in (
                            electric_startup_deadhead_kwh_by_slot.get(
                                slot_idx, []
                            )
                        )
                        if start_key[0] == vehicle.vehicle_id
                    )
                    return_deadhead_energy_expr = gp.quicksum(
                        return_kwh * end_arc[end_key]
                        for return_kwh, end_key in electric_return_deadhead_kwh_by_slot.get(slot_idx, [])
                        if end_key[0] == vehicle.vehicle_id
                    )
                    model.addConstr(
                        s_var[(vehicle.vehicle_id, next_slot_idx)]
                        == s_var[(vehicle.vehicle_id, slot_idx)]
                        + 0.95 * c_var[(vehicle.vehicle_id, slot_idx)] * timestep_h
                        - d_var[(vehicle.vehicle_id, slot_idx)] * timestep_h / 0.95
                        - trip_energy_expr
                        - startup_deadhead_energy_expr
                        - deadhead_energy_expr
                        - return_deadhead_energy_expr
                    )

                    # C12: no charging while vehicle is operating a trip in this slot.
                    running_expr = gp.quicksum(
                        y[(vehicle.vehicle_id, trip.trip_id)]
                        for trip in problem.trips
                        if (vehicle.vehicle_id, trip.trip_id) in y
                        and self._trip_active_in_slot(problem, trip.departure_min, trip.arrival_min, slot_idx)
                    )
                    model.addConstr(charge_on_var[(vehicle.vehicle_id, slot_idx)] <= 1 - running_expr)
                    away_terms = away_from_home_slot_terms.get(
                        (vehicle.vehicle_id, slot_idx), []
                    )
                    for away_var in away_terms:
                        model.addConstr(
                            charge_on_var[(vehicle.vehicle_id, slot_idx)]
                            <= 1 - away_var
                        )
                    proxy_terms = home_depot_slot_proxy_terms.get((vehicle.vehicle_id, slot_idx), [])
                    slot_day_idx = slot_idx // slots_per_day
                    assigned_day_indices = assignment_day_indices_by_vehicle.get(vehicle.vehicle_id, set())
                    if final_target_enabled or buffer_topup_enabled:
                        if not self._is_replenishment_slot_allowed(problem, slot_idx):
                            model.addConstr(charge_on_var[(vehicle.vehicle_id, slot_idx)] == 0)
                        elif proxy_terms:
                            model.addConstr(
                                charge_on_var[(vehicle.vehicle_id, slot_idx)] <= gp.quicksum(proxy_terms)
                            )
                        elif bool(getattr(vehicle, "available", True)) and slot_day_idx not in assigned_day_indices:
                            pass
                        else:
                            model.addConstr(charge_on_var[(vehicle.vehicle_id, slot_idx)] == 0)
                    elif proxy_terms:
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

            if bev_ids and slot_indices:
                vehicle_by_id = {v.vehicle_id: v for v in problem.vehicles}
                (
                    physical_charger_assignment_var,
                    physical_charger_power_var,
                    physical_charger_metadata,
                ) = self._add_physical_charger_assignment(
                    model=model,
                    gp=gp,
                    grb=GRB,
                    problem=problem,
                    vehicle_by_id=vehicle_by_id,
                    vehicle_ids=tuple(sorted(bev_ids)),
                    slot_indices=slot_indices,
                    charge_power_var=c_var,
                    charge_on_var=charge_on_var,
                    name_prefix="physical_charger",
                )
                ports_by_depot: Dict[str, float] = {}
                for charger in problem.chargers:
                    depot_id = str(charger.depot_id or "depot_default")
                    ports_by_depot[depot_id] = ports_by_depot.get(depot_id, 0.0) + float(
                        max(int(charger.simultaneous_ports or 1), 1)
                    )
                charge_ports_by_depot = dict(ports_by_depot)
                for slot_idx in slot_indices:
                    for depot_id, port_limit in ports_by_depot.items():
                        vehicle_ids = [
                            vehicle_id
                            for vehicle_id in bev_ids
                            if str(vehicle_by_id[vehicle_id].home_depot_id or "depot_default")
                            == depot_id
                        ]
                        soft_ratio = self._safe_nonnegative_float(
                            problem.metadata.get("charge_concurrency_soft_limit_ratio"),
                            default=0.7,
                        )
                        soft_limit = self._soft_charge_concurrency_limit(port_limit, soft_ratio)
                        excess_key = (depot_id, slot_idx)
                        slot_concurrency_excess_var[excess_key] = model.addVar(
                            lb=0.0, vtype=GRB.CONTINUOUS
                        )
                        model.addConstr(
                            slot_concurrency_excess_var[excess_key]
                            >= gp.quicksum(
                                charge_on_var[(vehicle_id, slot_idx)]
                                for vehicle_id in vehicle_ids
                            )
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
                        + float(
                            ice_startup_fuel_l_by_assignment.get(key, 0.0)
                        )
                        * start_arc[key]
                        + gp.quicksum(
                            self._deadhead_fuel_l(
                                problem,
                                vehicle,
                                from_trip_id,
                                trip.trip_id,
                            )
                            * x[(vehicle.vehicle_id, from_trip_id, trip.trip_id)]
                            for from_trip_id in assignment_trip_ids_by_vehicle.get(
                                vehicle.vehicle_id, []
                            )
                            if (
                                vehicle.vehicle_id,
                                from_trip_id,
                                trip.trip_id,
                            )
                            in x
                        )
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
                    else:
                        model.addConstr(
                            refuel_l_var[(vehicle.vehicle_id, slot_idx)] == 0
                        )
                    for away_var in away_from_home_slot_terms.get(
                        (vehicle.vehicle_id, slot_idx), []
                    ):
                        model.addConstr(
                            refuel_l_var[(vehicle.vehicle_id, slot_idx)]
                            <= max(refuel_per_slot_l, 0.0) * (1 - away_var)
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
                    startup_fuel_expr = gp.quicksum(
                        fuel_l * start_arc[start_key]
                        for fuel_l, start_key in ice_startup_fuel_l_by_slot.get(
                            slot_idx, []
                        )
                        if start_key[0] == vehicle.vehicle_id
                    )
                    return_fuel_expr = gp.quicksum(
                        fuel_l * end_arc[end_key]
                        for fuel_l, end_key in ice_return_fuel_l_by_slot.get(
                            slot_idx, []
                        )
                        if end_key[0] == vehicle.vehicle_id
                    )
                    model.addConstr(
                        fuel_l_var[(vehicle.vehicle_id, next_slot_idx)]
                        == fuel_l_var[(vehicle.vehicle_id, slot_idx)]
                        - trip_fuel_expr
                        - startup_fuel_expr
                        - deadhead_fuel_expr
                        - return_fuel_expr
                        + refuel_l_var[(vehicle.vehicle_id, slot_idx)]
                    )

                last_slot_idx = slot_indices[-1]
                terminal_return_fuel_expr = gp.quicksum(
                    fuel_l * end_arc[end_key]
                    for fuel_l, end_key in (
                        ice_terminal_return_fuel_l_by_vehicle.get(
                            vehicle.vehicle_id, []
                        )
                    )
                )
                last_slot_trip_fuel_expr = gp.quicksum(
                    self._trip_fuel_l(problem, vehicle, trip.trip_id)
                    * y[(vehicle.vehicle_id, trip.trip_id)]
                    for trip in problem.trips
                    if (vehicle.vehicle_id, trip.trip_id) in y
                    and self._slot_index(problem, trip.departure_min)
                    == last_slot_idx
                )
                last_slot_connection_fuel_expr = gp.quicksum(
                    self._deadhead_fuel_l(
                        problem, vehicle, from_trip_id, to_trip_id
                    )
                    * x[(vehicle.vehicle_id, from_trip_id, to_trip_id)]
                    for from_trip_id, to_trip_id in vehicle_arcs
                    if self._slot_index(
                        problem, trip_by_id[to_trip_id].departure_min
                    )
                    == last_slot_idx
                )
                last_slot_startup_fuel_expr = gp.quicksum(
                    fuel_l * start_arc[start_key]
                    for fuel_l, start_key in ice_startup_fuel_l_by_slot.get(
                        last_slot_idx, []
                    )
                    if start_key[0] == vehicle.vehicle_id
                )
                last_slot_return_fuel_expr = gp.quicksum(
                    fuel_l * end_arc[end_key]
                    for fuel_l, end_key in ice_return_fuel_l_by_slot.get(
                        last_slot_idx, []
                    )
                    if end_key[0] == vehicle.vehicle_id
                )
                terminal_fuel_expr = (
                    fuel_l_var[(vehicle.vehicle_id, last_slot_idx)]
                    + refuel_l_var[(vehicle.vehicle_id, last_slot_idx)]
                    - last_slot_trip_fuel_expr
                    - last_slot_startup_fuel_expr
                    - last_slot_connection_fuel_expr
                    - last_slot_return_fuel_expr
                    - terminal_return_fuel_expr
                )
                model.addConstr(terminal_fuel_expr >= reserve_l)
                model.addConstr(terminal_fuel_expr <= tank_cap_l)

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
                        soc_ub = max(_bess_soc_max_kwh(asset), soc_lb)
                        bess_soc_var[key] = model.addVar(lb=soc_lb, ub=soc_ub, vtype=GRB.CONTINUOUS)

                    vehicle_grid_terms = []
                    vehicle_pv_terms = []
                    vehicle_bess_terms = []
                    for vehicle_id in bev_ids_by_depot.get(depot_id, []):
                        charge_var = c_var.get((vehicle_id, slot_idx))
                        if charge_var is None:
                            continue
                        vehicle_key = (vehicle_id, slot_idx)
                        g2vehicle_var[vehicle_key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                        pv2vehicle_var[vehicle_key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                        bess2vehicle_var[vehicle_key] = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                        model.addConstr(
                            g2vehicle_var[vehicle_key]
                            + pv2vehicle_var[vehicle_key]
                            + bess2vehicle_var[vehicle_key]
                            == charge_var * timestep_h
                        )
                        vehicle_grid_terms.append(g2vehicle_var[vehicle_key])
                        vehicle_pv_terms.append(pv2vehicle_var[vehicle_key])
                        vehicle_bess_terms.append(bess2vehicle_var[vehicle_key])
                    model.addConstr(g2bus_var[key] == gp.quicksum(vehicle_grid_terms))
                    model.addConstr(pv2bus_var[key] == gp.quicksum(vehicle_pv_terms))
                    model.addConstr(bess2bus_var[key] == gp.quicksum(vehicle_bess_terms))

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
                    if not getattr(asset, "allow_pv_to_bess", True):
                        model.addConstr(pv2bess_var[key] == 0.0)
                    if not getattr(asset, "allow_bess_to_bus", True):
                        model.addConstr(bess2bus_var[key] == 0.0)

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
                    soc_ub = max(_bess_soc_max_kwh(asset), terminal_soc_floor)
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
                    final_soc_expr = (
                        bess_soc_var[last_key]
                        + eta_ch * (pv2bess_var[last_key] + g2bess_var[last_key])
                        - (bess2bus_var[last_key] / eta_dis)
                    )
                    model.addConstr(
                        final_soc_expr >= terminal_soc_floor
                    )
                    model.addConstr(
                        final_soc_expr <= soc_ub
                    )
                    terminal_soc_target = _bess_terminal_soc_target_kwh(
                        asset,
                        terminal_soc_floor=terminal_soc_floor,
                    )
                    if terminal_soc_target is not None:
                        terminal_tolerance = self._safe_nonnegative_float(
                            problem.metadata.get(
                                "bess_terminal_soc_tolerance_kwh"
                            ),
                            default=1.0e-6,
                        )
                        model.addConstr(
                            final_soc_expr
                            >= terminal_soc_target - terminal_tolerance
                        )
                        model.addConstr(
                            final_soc_expr
                            <= terminal_soc_target + terminal_tolerance
                        )
                        dev_var = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS)
                        bess_terminal_soc_deviation_var[depot_id] = dev_var
                        model.addConstr(dev_var >= final_soc_expr - terminal_soc_target)
                        model.addConstr(dev_var >= terminal_soc_target - final_soc_expr)

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
        fuel_weight = max(problem.objective_weights.fuel, 0.0)
        demand_weight = max(problem.objective_weights.demand, 0.0)
        vehicle_weight = max(problem.objective_weights.vehicle, 0.0)
        vehicle_usage_weight = max(problem.objective_weights.vehicle_usage, 0.0)
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
        opportunistic_topup_deficit_penalty_per_kwh = self._safe_nonnegative_float(
            problem.metadata.get("opportunistic_topup_deficit_penalty_yen_per_kwh"),
            default=500.0,
        )

        objective = gp.LinExpr()
        # O2: electricity cost based on actual charging source flows.
        price_by_slot = {slot.slot_index: slot.grid_buy_yen_per_kwh for slot in problem.price_slots}
        grid_to_bus_priority_penalty = self._safe_nonnegative_float(
            problem.metadata.get("grid_to_bus_priority_penalty_yen_per_kwh"),
            default=1000.0,
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
        pv_marginal_charge_cost = self._safe_nonnegative_float(
            problem.metadata.get("pv_marginal_charge_cost_yen_per_kwh"),
            default=0.0,
        )
        # A configured zero is a valid economic assumption.  Do not replace it
        # with a hidden penalty, because that changes the optimization problem.
        pv_curtail_penalty_auto_defaulted = False
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
                for var in pv2bus_var.values():
                    objective += energy_weight * pv_marginal_charge_cost * var
                for var in pv2bess_var.values():
                    objective += energy_weight * pv_marginal_charge_cost * var
            if curtail_penalty > 0.0 and component_flags.get("electricity_cost", True):
                for var in pv_curt_var.values():
                    objective += energy_weight * curtail_penalty * var
            if contract_overage_penalty > 0.0 and component_flags.get("contract_overage_penalty", True):
                for var in contract_over_limit_var.values():
                    objective += contract_overage_penalty * var
            for depot_id, var in bess_terminal_soc_deviation_var.items():
                asset = effective_depot_energy_assets.get(depot_id)
                penalty = max(
                    float(getattr(asset, "bess_terminal_soc_deviation_penalty_yen_per_kwh", 0.0) or 0.0),
                    0.0,
                )
                if penalty > 0.0:
                    objective += energy_weight * penalty * var
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
                objective += fuel_weight * diesel_price * fuel_l * var

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
                objective += fuel_weight * diesel_price * deadhead_km * fuel_rate * var
            for assignment_key, fuel_l in (
                ice_startup_fuel_l_by_assignment.items()
            ):
                objective += (
                    fuel_weight
                    * diesel_price
                    * fuel_l
                    * start_arc[assignment_key]
                )
            for assignment_key, fuel_l in (
                ice_return_fuel_l_by_assignment.items()
            ):
                objective += (
                    fuel_weight
                    * diesel_price
                    * fuel_l
                    * end_arc[assignment_key]
                )

        # O3: demand charge cost.
        if (
            component_flags.get("demand_charge_cost", True)
            and w_on_var is not None
            and w_off_var is not None
        ):
            objective += demand_weight * problem.scenario.demand_charge_on_peak_horizon_yen_per_kw * w_on_var
            objective += demand_weight * problem.scenario.demand_charge_off_peak_horizon_yen_per_kw * w_off_var

        if component_flags.get("vehicle_fixed_cost", True):
            for vehicle in problem.vehicles:
                objective += vehicle_weight * vehicle.fixed_use_cost_jpy * used_vehicle[vehicle.vehicle_id]

        vehicle_usage_unit_cost = self._safe_nonnegative_float(
            problem.metadata.get("vehicle_usage_cost_jpy_per_used_bus"),
            default=0.0,
        )
        if component_flags.get("vehicle_usage_cost", True) and vehicle_usage_unit_cost > 0.0:
            for var in used_vehicle_day.values():
                objective += vehicle_usage_weight * vehicle_usage_unit_cost * var

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

        # Weather strategy bias is an objective-only policy term. It is not an
        # accounting fuel/electricity/asset cost and never changes eligibility.
        weather_bias_by_vehicle_type: Dict[str, float] = {}
        for vehicle in problem.vehicles:
            weather_bias_by_vehicle_type[str(vehicle.vehicle_type)] = weather_assignment_objective_bias(
                problem.metadata,
                vehicle.vehicle_type,
            )
        if any(abs(value) > 1.0e-9 for value in weather_bias_by_vehicle_type.values()):
            for (vehicle_id, _trip_id), var in y.items():
                vehicle = vehicle_by_id.get(str(vehicle_id))
                if vehicle is None:
                    continue
                objective += weather_bias_by_vehicle_type.get(str(vehicle.vehicle_type), 0.0) * var

        # CO₂ objective/cost: in CO2 mode, co2_price_per_kg is treated as a
        # positive scaling factor (defaulted to 1.0 upstream when omitted).
        co2_price = max(problem.scenario.co2_price_per_kg, 0.0)
        if objective_mode == "co2" and co2_price <= 0.0:
            co2_price = 1.0
        ice_co2_kg_per_l = max(problem.scenario.ice_co2_kg_per_l, 0.0)

        def _ice_co2_kg_per_l_for_vehicle(vehicle: Any) -> float:
            vehicle_type = vehicle_type_by_id.get(str(getattr(vehicle, "vehicle_type", "")))
            if vehicle_type is not None:
                value = max(float(vehicle_type.co2_emission_kg_per_l or 0.0), 0.0)
                if value > 0.0:
                    return value
            return ice_co2_kg_per_l

        if co2_price > 0 and component_flags.get("co2_cost", True):
            # ICE CO₂ from trip fuel consumption.
            for (vehicle_id, trip_id), var in y.items():
                vehicle = next((v for v in problem.vehicles if v.vehicle_id == vehicle_id), None)
                if vehicle is None or vehicle.vehicle_type.upper() in {"BEV", "PHEV", "FCEV"}:
                    continue
                trip = trip_by_id.get(trip_id)
                if trip is None:
                    continue
                fuel_l = self._trip_fuel_l(problem, vehicle, trip_id)
                objective += co2_price * _ice_co2_kg_per_l_for_vehicle(vehicle) * fuel_l * var
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
                objective += co2_price * _ice_co2_kg_per_l_for_vehicle(vehicle) * dh_km * fuel_rate * var
            for assignment_key, fuel_l in (
                ice_startup_fuel_l_by_assignment.items()
            ):
                vehicle = vehicle_by_id.get(str(assignment_key[0]))
                if vehicle is None:
                    continue
                objective += (
                    co2_price
                    * _ice_co2_kg_per_l_for_vehicle(vehicle)
                    * fuel_l
                    * start_arc[assignment_key]
                )
            for assignment_key, fuel_l in (
                ice_return_fuel_l_by_assignment.items()
            ):
                vehicle = vehicle_by_id.get(str(assignment_key[0]))
                if vehicle is None:
                    continue
                objective += (
                    co2_price
                    * _ice_co2_kg_per_l_for_vehicle(vehicle)
                    * fuel_l
                    * end_arc[assignment_key]
                )
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

        if (
            opportunistic_topup_deficit_penalty_per_kwh > 0.0
            and opportunistic_topup_deficit_var
            and component_flags.get("opportunistic_topup_deficit_penalty", True)
        ):
            for var in opportunistic_topup_deficit_var.values():
                objective += opportunistic_topup_deficit_penalty_per_kwh * var
        
        # SOC bound violation penalty is available only in explicit diagnostic slack mode.
        soc_violation_penalty_per_kwh = self._safe_nonnegative_float(
            problem.metadata.get("soc_violation_penalty_per_kwh"),
            default=1000.0,
        )
        if soc_violation_penalty_per_kwh > 0.0 and component_flags.get("soc_violation_penalty", True):
            for var in soc_bound_violation_var.values():
                objective += soc_violation_penalty_per_kwh * var

        if (
            allow_partial_service
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

        # Return-leg bonus: subtract reward when a vehicle makes an efficient
        # outbound→return (turnaround) connection on the same route family.
        # Condition: same route_family_code + trip_i.destination == trip_j.origin (same stop).
        _return_leg_bonus_weight = max(
            float(getattr(problem.objective_weights, "return_leg_bonus", 0.0) or 0.0), 0.0
        )
        if _return_leg_bonus_weight > 0.0 and x:
            _RETURN_LEG_BONUS_BASE_YEN = 500.0
            turnaround_pairs: Dict[Tuple[str, str], float] = {}
            for trip_i in problem.trips:
                dt_i = dispatch_trip_by_id.get(trip_i.trip_id)
                fam_i = (
                    str(getattr(dt_i, "route_family_code", "") or "").strip()
                    or str(getattr(trip_i, "route_family_code", "") or "").strip()
                )
                if not fam_i:
                    continue
                dest_i = (
                    str(getattr(dt_i, "destination", "") or "").strip()
                    or str(getattr(trip_i, "destination", "") or "").strip()
                )
                if not dest_i:
                    continue
                for trip_j_id in problem.feasible_connections.get(trip_i.trip_id, ()):
                    pt_j = trip_by_id.get(trip_j_id)
                    if pt_j is None:
                        continue
                    dt_j = dispatch_trip_by_id.get(trip_j_id)
                    fam_j = (
                        str(getattr(dt_j, "route_family_code", "") or "").strip()
                        or str(getattr(pt_j, "route_family_code", "") or "").strip()
                    )
                    if fam_i != fam_j:
                        continue
                    orig_j = (
                        str(getattr(dt_j, "origin", "") or "").strip()
                        or str(getattr(pt_j, "origin", "") or "").strip()
                    )
                    if dest_i == orig_j:
                        turnaround_pairs[(trip_i.trip_id, trip_j_id)] = _RETURN_LEG_BONUS_BASE_YEN
            for (vehicle_id, from_trip_id, to_trip_id), var in x.items():
                bonus = turnaround_pairs.get((from_trip_id, to_trip_id), 0.0)
                if bonus > 0.0:
                    objective -= _return_leg_bonus_weight * bonus * var

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

        if allow_partial_service:
            coverage_objective = gp.quicksum(unserved[trip.trip_id] for trip in problem.trips)
            model.ModelSense = GRB.MINIMIZE
            model.setObjectiveN(coverage_objective, index=0, priority=2, name="coverage")
            model.setObjectiveN(objective, index=1, priority=1, name="secondary_cost")
        else:
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
            "arc_pruning_summary": arc_pruning_summary,
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
        incumbent_unserved_count = 0 if has_feasible_incumbent and not allow_partial_service else None
        if has_feasible_incumbent:
            try:
                incumbent_unserved_count = int(
                    round(sum(float(unserved[trip.trip_id].X or 0.0) for trip in problem.trips))
                )
            except Exception:
                incumbent_unserved_count = None
        presolve_reduction_summary = {
            "initial_num_vars": int(pre_stats.get("num_vars", 0) or 0),
            "initial_num_constrs": int(pre_stats.get("num_constrs", 0) or 0),
            "initial_num_bin_vars": int(pre_stats.get("num_binary_vars", 0) or 0),
            "initial_num_int_vars": int(pre_stats.get("num_integer_vars", 0) or 0),
        }
        best_bound = self._model_bound(model)
        final_gap = self._model_gap(model) if has_feasible_incumbent else None
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
            and not bool(getattr(config, "research_run", False))
            and unserved_penalty_weight > 0.0
            and problem.baseline_plan is not None
            and len(problem.baseline_plan.served_trip_ids) > 0
        ):
            full_unserved_count = int(len(problem.trips))
            if incumbent_unserved_count is not None and incumbent_unserved_count >= full_unserved_count:
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
            if model.Status == GRB.TIME_LIMIT and not bool(getattr(config, "research_run", False)):
                baseline_fallback = self._baseline_fallback(
                    problem,
                    fallback_status="time_limit_baseline",
                    source="dispatch_baseline_after_time_limit_no_incumbent",
                    solver_status=solver_status,
                    relaxed_partial_service=bool(relaxed_partial_service),
                )
                if baseline_fallback is not None:
                    return baseline_fallback
            reported_status = solver_status
            if bool(getattr(config, "research_run", False)):
                if model.Status == GRB.TIME_LIMIT:
                    reported_status = "TIME_LIMIT_WITHOUT_VALID_SOLUTION"
                elif solver_status in {"infeasible", "inf_or_unbd"}:
                    reported_status = "INFEASIBLE"
                else:
                    reported_status = "NO_VALID_INCUMBENT"
            empty = AssignmentPlan(
                duties=(),
                charging_slots=(),
                served_trip_ids=(),
                unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips)),
                metadata={
                    "source": "milp_gurobi",
                    "status": reported_status,
                    "auto_relaxed_allow_partial_service": bool(relaxed_partial_service),
                    "service_coverage_mode": service_coverage_mode,
                    "allow_partial_service": bool(allow_partial_service),
                    "debug_mode": bool(getattr(config, "debug_mode", False)),
                    "research_run": bool(getattr(config, "research_run", False)),
                    "result_class": "debug_result" if bool(getattr(config, "debug_mode", False)) else "optimization_result",
                    "research_kpi_eligible": not bool(getattr(config, "debug_mode", False)),
                    "strict_coverage_enforced": service_coverage_mode == "strict",
                    "startup_infeasible_assignment_count": len(startup_infeasible_trip_ids),
                    "startup_infeasible_trip_ids": tuple(sorted(startup_infeasible_trip_ids)),
                    "startup_infeasible_vehicle_ids": tuple(sorted(startup_infeasible_vehicle_ids)),
                    "arc_pruning_summary": arc_pruning_summary,
                    "successor_pruning_enabled": bool(arc_pruning_summary.get("successor_pruning_enabled", False)),
                    "milp_max_successors_per_trip": arc_pruning_summary.get("milp_max_successors_per_trip"),
                },
            )
            return (
                MILPSolverOutcome(
                    solver_status=reported_status,
                    used_backend=self.backend_name,
                    supports_exact_milp=_supports_full_candidate_network_exact_milp(
                        arc_pruning_summary
                    ),
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
        bess_soc_start_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        bess_soc_end_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        contract_over_limit_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
        vehicle_soc_kwh_by_vehicle_slot: Dict[str, Dict[int, float]] = {}
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
            asset = effective_depot_energy_assets.get(depot_id)
            eta_ch = max(float(getattr(asset, "bess_charge_efficiency", 0.95) or 0.95), 1.0e-6)
            eta_dis = max(float(getattr(asset, "bess_discharge_efficiency", 0.95) or 0.95), 1.0e-6)
            soc_start = max(_var_val(var), 0.0)
            charge_in = max(_var_val(pv2bess_var.get((depot_id, slot_idx))), 0.0)
            charge_in += max(_var_val(g2bess_var.get((depot_id, slot_idx))), 0.0)
            discharge_out = max(_var_val(bess2bus_var.get((depot_id, slot_idx))), 0.0)
            soc_end = max(soc_start + eta_ch * charge_in - (discharge_out / eta_dis), 0.0)
            bess_soc_start_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = soc_start
            bess_soc_end_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = soc_end
            bess_soc_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = soc_end
        for (depot_id, slot_idx), var in contract_over_limit_var.items():
            contract_over_limit_kwh_by_depot_slot.setdefault(depot_id, {})[slot_idx] = max(_var_val(var), 0.0)
        for (vehicle_id, slot_idx), var in s_var.items():
            vehicle_soc_kwh_by_vehicle_slot.setdefault(vehicle_id, {})[slot_idx] = max(_var_val(var), 0.0)

        bess_terminal_soc_deviation_kwh_by_depot = {
            str(depot_id): max(_var_val(var), 0.0)
            for depot_id, var in bess_terminal_soc_deviation_var.items()
        }
        bess_terminal_soc_target_kwh_by_depot = {
            str(depot_id): target
            for depot_id, asset in effective_depot_energy_assets.items()
            if bool(getattr(asset, "bess_enabled", False))
            for target in (
                _bess_terminal_soc_target_kwh(
                    asset,
                    terminal_soc_floor=max(
                        float(getattr(asset, "bess_terminal_soc_min_kwh", 0.0) or 0.0),
                        float(getattr(asset, "bess_soc_min_kwh", 0.0) or 0.0),
                    ),
                ),
            )
            if target is not None
        }

        opportunistic_topup_deficit_kwh_by_vehicle_day: Dict[Tuple[str, int], float] = {}
        for (vehicle_id, day_idx), var in opportunistic_topup_deficit_var.items():
            opportunistic_topup_deficit_kwh_by_vehicle_day[(vehicle_id, day_idx)] = max(_var_val(var), 0.0)
        opportunistic_topup_unfilled_kwh = sum(opportunistic_topup_deficit_kwh_by_vehicle_day.values())
        opportunistic_topup_unfilled_vehicle_day_ids = tuple(
            sorted(
                f"{vehicle_id}:d{day_idx}"
                for (vehicle_id, day_idx), value in opportunistic_topup_deficit_kwh_by_vehicle_day.items()
                if value > 1.0e-6
            )
        )
        opportunistic_topup_unfilled_vehicle_ids = tuple(
            sorted(
                {
                    vehicle_id
                    for (vehicle_id, _day_idx), value in opportunistic_topup_deficit_kwh_by_vehicle_day.items()
                    if value > 1.0e-6
                }
            )
        )

        if c_var and bev_ids:
            vehicle_by_id = {v.vehicle_id: v for v in problem.vehicles}
            for slot_idx in slot_indices:
                for vehicle_id in bev_ids:
                    var = c_var.get((vehicle_id, slot_idx))
                    if var is None:
                        continue
                    vehicle_kw = max(_var_val(var), 0.0)
                    if vehicle_kw <= 0.0:
                        continue
                    vehicle = vehicle_by_id.get(vehicle_id)
                    depot_id = str(getattr(vehicle, "home_depot_id", "") or "depot_default")
                    selected_charger_id = next(
                        (
                            charger_id
                            for (candidate_vehicle_id, charger_id, candidate_slot_idx), assignment in physical_charger_assignment_var.items()
                            if candidate_vehicle_id == vehicle_id
                            and candidate_slot_idx == slot_idx
                            and _var_val(assignment) > 0.5
                        ),
                        None,
                    )
                    if selected_charger_id is None:
                        raise RuntimeError(
                            "Positive charging power has no selected physical charger: "
                            f"vehicle={vehicle_id}, slot={slot_idx}"
                        )
                    vehicle_key = (vehicle_id, slot_idx)
                    bess_kwh = max(_var_val(bess2vehicle_var.get(vehicle_key)), 0.0)
                    pv_kwh = max(_var_val(pv2vehicle_var.get(vehicle_key)), 0.0)
                    grid_kwh = max(_var_val(g2vehicle_var.get(vehicle_key)), 0.0)
                    if bess_kwh > 1.0e-9:
                        lat, lon = _depot_latlon(depot_id)
                        charging_slots.append(
                            ChargingSlot(
                                vehicle_id=vehicle_id,
                                slot_index=slot_idx,
                                charger_id=selected_charger_id,
                                energy_source="bess",
                                charge_kw=bess_kwh / timestep_h,
                                discharge_kw=0.0,
                                charging_depot_id=depot_id,
                                charging_latitude=lat,
                                charging_longitude=lon,
                            )
                        )
                    if pv_kwh > 1.0e-9:
                        lat, lon = _depot_latlon(depot_id)
                        charging_slots.append(
                            ChargingSlot(
                                vehicle_id=vehicle_id,
                                slot_index=slot_idx,
                                charger_id=selected_charger_id,
                                energy_source="pv",
                                charge_kw=pv_kwh / timestep_h,
                                discharge_kw=0.0,
                                charging_depot_id=depot_id,
                                charging_latitude=lat,
                                charging_longitude=lon,
                            )
                        )
                    if grid_kwh > 1.0e-9:
                        lat, lon = _depot_latlon(depot_id)
                        charging_slots.append(
                            ChargingSlot(
                                vehicle_id=vehicle_id,
                                slot_index=slot_idx,
                                charger_id=selected_charger_id,
                                energy_source="grid",
                                charge_kw=grid_kwh / timestep_h,
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
        diagnostic_slack_summary = {
            "unserved_trip_count": int(len(unserved_trip_ids)),
            "soc_lower_deficit_kwh": round(
                sum(
                    max(_var_val(var), 0.0)
                    for (_vehicle_id, _slot_idx, kind), var in soc_bound_violation_var.items()
                    if kind == "lower"
                ),
                6,
            ),
            "soc_upper_excess_kwh": round(
                sum(
                    max(_var_val(var), 0.0)
                    for (_vehicle_id, _slot_idx, kind), var in soc_bound_violation_var.items()
                    if kind == "upper"
                ),
                6,
            ),
            "contract_over_limit_kwh": round(
                sum(
                    max(value, 0.0)
                    for slot_map in contract_over_limit_kwh_by_depot_slot.values()
                    for value in slot_map.values()
                ),
                6,
            ),
            "soft_charger_concurrency_excess_sessions": round(
                sum(max(_var_val(var), 0.0) for var in slot_concurrency_excess_var.values()),
                6,
            ),
        }

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
            vehicle_soc_kwh_by_vehicle_slot=vehicle_soc_kwh_by_vehicle_slot,
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
                "pv_curtail_penalty_yen_per_kwh": curtail_penalty,
                "bess_terminal_soc_target_kwh_by_depot": bess_terminal_soc_target_kwh_by_depot,
                "bess_terminal_soc_deviation_kwh_by_depot": bess_terminal_soc_deviation_kwh_by_depot,
                "bess_terminal_soc_deviation_kwh": round(sum(bess_terminal_soc_deviation_kwh_by_depot.values()), 6),
                "bess_soc_start_kwh_by_depot_slot": bess_soc_start_kwh_by_depot_slot,
                "bess_soc_end_kwh_by_depot_slot": bess_soc_end_kwh_by_depot_slot,
                "vehicle_usage_cost_jpy_per_used_bus": vehicle_usage_unit_cost,
                "minimum_used_bev_count": minimum_used_bev_count,
                "minimum_used_bev_count_policy_enabled": (
                    minimum_used_bev_count > 0
                ),
                "pv_curtail_penalty_auto_defaulted": pv_curtail_penalty_auto_defaulted,
                "charge_session_start_penalty_yen": charge_session_start_penalty,
                "slot_concurrency_penalty_yen": slot_concurrency_penalty,
                "early_charge_penalty_yen_per_kwh": early_charge_penalty_per_kwh,
                "charge_to_upper_buffer_penalty_yen_per_kwh": charge_upper_buffer_penalty_per_kwh,
                "opportunistic_topup_deficit_penalty_yen_per_kwh": opportunistic_topup_deficit_penalty_per_kwh,
                "soc_violation_slack_enabled": bool(soc_bound_violation_var),
                "soc_violation_penalty_per_kwh": soc_violation_penalty_per_kwh,
                "diagnostic_slack_summary": diagnostic_slack_summary,
                "opportunistic_topup_unfilled_kwh": round(opportunistic_topup_unfilled_kwh, 6),
                "opportunistic_topup_unfilled_vehicle_day_ids": opportunistic_topup_unfilled_vehicle_day_ids,
                "opportunistic_topup_unfilled_vehicle_ids": opportunistic_topup_unfilled_vehicle_ids,
                "source_provenance_exact": True,
                # Source-flow variables are depot/slot aggregates.  The
                # physical charger assignment identifies a charger, not the
                # grid/PV/BESS source used by each vehicle, so vehicle-level
                # source splits must remain explicitly derived.
                "vehicle_source_provenance_exact": False,
                "vehicle_source_allocation_policy": "proportional_by_depot_timestep",
                "derived_source_split": False,
                **physical_charger_metadata,
                "arc_pruning_summary": arc_pruning_summary,
                "integrated_single_path_redundancy_elimination_applied": (
                    integrated_single_path_redundancy_elimination_applied
                ),
                "integrated_fragment_pairwise_constraint_count": (
                    integrated_fragment_pairwise_constraint_count
                ),
                "integrated_fragment_occupancy_constraint_count": (
                    integrated_fragment_occupancy_constraint_count
                ),
                "integrated_overlap_clique_constraint_count": (
                    integrated_overlap_clique_constraint_count
                ),
                "successor_pruning_enabled": bool(arc_pruning_summary.get("successor_pruning_enabled", False)),
                "milp_max_successors_per_trip": arc_pruning_summary.get("milp_max_successors_per_trip"),
                "service_coverage_mode": service_coverage_mode,
                "allow_partial_service": bool(allow_partial_service),
                "debug_mode": bool(getattr(config, "debug_mode", False)),
                "result_class": "debug_result" if bool(getattr(config, "debug_mode", False)) else "optimization_result",
                "research_kpi_eligible": not bool(getattr(config, "debug_mode", False)),
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
                supports_exact_milp=_supports_full_candidate_network_exact_milp(
                    arc_pruning_summary
                ),
                **common_outcome_kwargs,
            ),
            plan,
        )

    def _solve_charging_only(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> Tuple[MILPSolverOutcome, AssignmentPlan]:
        """Phase 1: fixed vehicle-trip assignment, optimize charging/PV/BESS/contract only.

        Reuses the thesis Stage 2 charging-dispatch MILP with the assignment
        supplied by ``config.fixed_assignment`` rather than solving Stage 1.
        Acts as the canonical equivalent of the legacy "mode_A_journey_charge"
        flow but drives the thesis Stage 2 MILP directly.
        """
        fixed_assignment = getattr(config, "fixed_assignment", None)
        if fixed_assignment is None:
            baseline = problem.baseline_plan
            if baseline is None or not bool(getattr(baseline, "served_trip_ids", ())):
                return self._empty_unserved_outcome(
                    problem,
                    config,
                    reason="phase1_fixed_assignment_missing",
                    status="phase1_fixed_assignment_missing",
                )
            fixed_assignment = baseline
        fixed_assignment, contract_error = self._normalize_phase1_fixed_assignment(
            problem,
            fixed_assignment,
        )
        if contract_error:
            return self._empty_unserved_outcome(
                problem,
                config,
                reason=contract_error,
                status=contract_error,
            )
        if not is_gurobi_available():
            return self._gurobi_unavailable_phase_outcome(
                problem,
                config,
                fixed_assignment,
                phase_label="phase1_charging_only",
            )
        # Stage 2 helper expects a stage1_plan plus Stage 1 status metadata.
        # For Phase 1 the assignment is externally fixed, so we synthesize a
        # deterministic status that downstream KPI readers treat as non-MILP.
        slot_indices = sorted({slot.slot_index for slot in problem.price_slots})
        slots_per_day = len(slot_indices) or 1
        outcome, plan = self._solve_thesis_stage2_charging_dispatch(
            problem,
            config,
            fixed_assignment,
            stage1_status="phase1_fixed_assignment",
            stage1_gap=None,
            stage1_bound=None,
            stage1_objective_value=None,
            stage1_runtime_sec=0.0,
            slots_per_day=slots_per_day,
        )
        plan = self._stamp_phase_metadata(
            plan,
            config,
            phase="phase1_charging_only",
            result_class="optimization_result",
        )
        return outcome, plan

    def _solve_assignment_only(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> Tuple[MILPSolverOutcome, AssignmentPlan]:
        """Phase 2: optimize vehicle-trip assignment only (no charging/SOC decisions).

        Executes the Stage 1 vehicle-scheduling MILP from the thesis two-stage
        path and returns its assignment plan without invoking Stage 2. Charging/SOC
        feasibility is deferred to a Phase 1 or Phase 3 follow-on run.
        """
        if not is_gurobi_available():
            return self._gurobi_unavailable_phase_outcome(
                problem,
                config,
                getattr(config, "fixed_assignment", None),
                phase_label="phase2_assignment_only",
            )
        outcome, plan = self._solve_thesis_two_stage(
            problem,
            config,
            stage2_enabled=False,
            diagnostic_mode=bool(getattr(config, "diagnostic_mode", False)),
        )
        plan = self._stamp_phase_metadata(
            plan,
            config,
            phase="phase2_assignment_only",
            result_class="assignment_only_result",
        )
        return outcome, plan

    def _solve_diagnostic(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> Tuple[MILPSolverOutcome, AssignmentPlan]:
        """Diagnostic phase: run the integrated debug MILP and tag it as diagnostic.

        This uses the existing unserved/SOC/contract softening hooks where they
        already exist. Charger-port and some BESS constraints remain hard, so the
        returned binding report is a diagnostic summary, not an IIS proof.
        """
        diagnostic_metadata = dict(problem.metadata or {})
        diagnostic_metadata["allow_soc_violation_slack"] = True
        diagnostic_metadata["use_soft_soc_constraint"] = True
        diagnostic_metadata["enable_contract_overage_penalty"] = True
        diagnostic_problem = replace(problem, metadata=diagnostic_metadata)
        diagnostic_config = replace(
            config,
            phase="",
            thesis_mode=False,
            debug_mode=True,
            diagnostic_mode=True,
            allow_postsolve_repair=False,
        )
        outcome, plan = self.solve(diagnostic_problem, diagnostic_config)
        plan = self._stamp_phase_metadata(
            plan,
            diagnostic_config,
            phase="diagnostic",
            result_class="debug_result",
        )
        meta = dict(plan.metadata or {})
        meta["diagnostic_relaxations_requested"] = (
            "unserved_trip_slack",
            "ev_soc_bound_slack",
            "contract_overage_slack",
        )
        meta["diagnostic_limitations"] = (
            "charger port limits remain hard in the current diagnostic path",
            "BESS feasibility is summarized from validation metrics, not IIS slack",
        )
        return outcome, replace(plan, metadata=meta)

    def _normalize_phase1_fixed_assignment(
        self,
        problem: CanonicalOptimizationProblem,
        fixed_assignment: AssignmentPlan,
    ) -> Tuple[AssignmentPlan, str]:
        if not fixed_assignment.duties:
            return fixed_assignment, "phase1_fixed_assignment_duties_missing"
        duty_trip_ids: List[str] = []
        for duty in fixed_assignment.duties:
            duty_trip_ids.extend(str(trip_id) for trip_id in duty.trip_ids)
        if not duty_trip_ids:
            return fixed_assignment, "phase1_fixed_assignment_duties_missing"
        seen: Set[str] = set()
        duplicates: Set[str] = set()
        for trip_id in duty_trip_ids:
            if trip_id in seen:
                duplicates.add(trip_id)
            seen.add(trip_id)
        if duplicates:
            return fixed_assignment, "phase1_fixed_assignment_duplicate_trips"
        expected_trip_ids = set(str(trip_id) for trip_id in problem.eligible_trip_ids())
        assigned_trip_ids = set(duty_trip_ids)
        if assigned_trip_ids - expected_trip_ids:
            return fixed_assignment, "phase1_fixed_assignment_unknown_trips"
        if expected_trip_ids - assigned_trip_ids:
            return fixed_assignment, "phase1_fixed_assignment_incomplete"
        if tuple(fixed_assignment.unserved_trip_ids or ()):
            return fixed_assignment, "phase1_fixed_assignment_has_unserved_trips"
        declared_served = set(str(trip_id) for trip_id in (fixed_assignment.served_trip_ids or ()))
        if declared_served and declared_served != assigned_trip_ids:
            return fixed_assignment, "phase1_fixed_assignment_served_ids_mismatch"
        if not declared_served:
            fixed_assignment = replace(
                fixed_assignment,
                served_trip_ids=tuple(sorted(assigned_trip_ids)),
                unserved_trip_ids=(),
            )
        return fixed_assignment, ""

    def _stamp_phase_metadata(
        self,
        plan: AssignmentPlan,
        config: OptimizationConfig,
        *,
        phase: str,
        result_class: Optional[str] = None,
    ) -> AssignmentPlan:
        meta = dict(plan.metadata or {})
        meta["phase"] = phase
        meta["diagnostic_mode"] = bool(getattr(config, "diagnostic_mode", False) or phase == "diagnostic")
        if result_class is None:
            if phase == "diagnostic":
                result_class = "debug_result"
            elif phase == "phase2_assignment_only":
                result_class = "assignment_only_result"
            else:
                result_class = str(meta.get("result_class") or "optimization_result")
        meta["result_class"] = result_class
        if phase == "phase2_assignment_only":
            meta["optimization_structure"] = "assignment_only"
            meta["stage2_solver_status"] = str(meta.get("stage2_solver_status") or "not_run_assignment_only")
            meta["charging_dispatch_evaluated"] = False
            meta["soc_constraints_evaluated"] = False
            meta["supports_assignment_milp"] = True
            meta["research_kpi_eligible"] = False
        elif phase == "phase1_charging_only":
            meta["optimization_structure"] = "charging_only"
            meta["charging_dispatch_evaluated"] = True
            meta["soc_constraints_evaluated"] = True
            meta["research_kpi_eligible"] = False
        elif phase == "phase3_two_stage":
            # A two-stage feasible schedule is publishable for feasibility and
            # constraint analysis, but not as a globally optimized cost KPI.
            meta["research_kpi_eligible"] = False
            meta["research_cost_kpi_eligible"] = False
        elif phase == "diagnostic":
            meta["research_kpi_eligible"] = False
        else:
            meta["research_kpi_eligible"] = bool(meta.get("research_kpi_eligible", True)) and not bool(
                getattr(config, "diagnostic_mode", False)
            )
        return replace(plan, metadata=meta)

    def _stamp_phase_outcome(
        self,
        outcome: MILPSolverOutcome,
        config: OptimizationConfig,
        *,
        phase: str,
        result_class: str,
    ) -> MILPSolverOutcome:
        meta_phase = {"phase": phase, "result_class": result_class}
        # Outcome is a frozen dataclass; we cannot attach metadata directly, so
        # the engine/BFF will pick up phase from solver_metadata when assembling
        # the run payload. Returning the outcome unchanged here keeps the data
        # contract minimal; phase tagging lives on plan.metadata plus the MILP
        # engine's solver_metadata dict.
        return outcome

    def _empty_unserved_outcome(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        *,
        reason: str,
        status: str,
    ) -> Tuple[MILPSolverOutcome, AssignmentPlan]:
        plan = AssignmentPlan(
            duties=(),
            served_trip_ids=(),
            unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips)),
            metadata={
                "source": "canonical_milp_adapter",
                "status": status,
                "reason": reason,
                "phase": normalize_phase(getattr(config, "phase", "")) if str(getattr(config, "phase", "") or "").strip() else "",
                "result_class": "postsolve_infeasible",
                "research_run": bool(getattr(config, "research_run", False)),
                "research_kpi_eligible": False,
                "fallback_applied": False,
                "phase_contract_error": reason,
            },
        )
        return (
            MILPSolverOutcome(
                solver_status=status,
                used_backend=self.backend_name,
                supports_exact_milp=False,
                fallback_reason=reason,
            ),
            plan,
        )

    def _gurobi_unavailable_phase_outcome(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        fixed_assignment: Optional[AssignmentPlan],
        *,
        phase_label: str,
    ) -> Tuple[MILPSolverOutcome, AssignmentPlan]:
        if bool(getattr(config, "research_run", False)):
            return self._empty_unserved_outcome(
                problem,
                config,
                reason=f"gurobi_unavailable_{phase_label}",
                status="NO_VALID_INCUMBENT",
            )
        baseline = fixed_assignment or problem.baseline_plan or AssignmentPlan()
        baseline_metadata = dict(baseline.metadata or {})
        baseline_metadata.update(
            {
                "phase": phase_label,
                "status": "gurobi_unavailable",
                "result_class": "baseline_fallback",
                "research_kpi_eligible": False,
            }
        )
        return (
            MILPSolverOutcome(
                solver_status="gurobi_unavailable",
                used_backend="none",
                supports_exact_milp=False,
                fallback_reason=f"gurobi_unavailable_{phase_label}",
            ),
            replace(baseline, metadata=baseline_metadata),
        )

    def _solve_thesis_two_stage(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        *,
        stage2_enabled: bool = True,
        diagnostic_mode: bool = False,
    ) -> Tuple[MILPSolverOutcome, AssignmentPlan]:
        if not is_gurobi_available():
            status = "NO_VALID_INCUMBENT" if bool(getattr(config, "research_run", False)) else "gurobi_unavailable"
            return (
                MILPSolverOutcome(
                    solver_status=status,
                    used_backend="none",
                    supports_exact_milp=False,
                    fallback_reason="gurobi_unavailable",
                ),
                AssignmentPlan(
                    duties=(),
                    served_trip_ids=(),
                    unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips)),
                    metadata={
                        "source": "milp_gurobi_two_stage",
                        "status": status,
                        "thesis_mode": True,
                        "stage1_solver_status": None,
                        "stage1_has_feasible_incumbent": False,
                        "stage1_objective": None,
                        "stage1_best_bound": None,
                        "stage1_mip_gap_ratio": None,
                        "stage1_runtime_seconds": None,
                        "stage2_solver_status": "not_run_gurobi_unavailable",
                        "stage2_has_feasible_incumbent": False,
                        "stage2_objective": None,
                        "stage2_best_bound": None,
                        "stage2_mip_gap_ratio": None,
                        "stage2_runtime_seconds": None,
                        "stage1_feasible": False,
                        "stage2_feasible": False,
                        "supports_two_stage_milp": False,
                        "supports_integrated_exact_milp": False,
                        "research_kpi_eligible": False,
                    },
                ),
            )

        gp, GRB = ensure_gurobi()
        total_started = time.perf_counter()
        stage_time_limit = _resolved_stage_time_limit_sec(config, stage=1)
        stage1 = gp.Model("thesis_stage1_vehicle_scheduling")
        stage1.Params.OutputFlag = 0
        stage1.Params.TimeLimit = stage_time_limit
        stage1.Params.MIPGap = max(float(config.mip_gap), 0.0)
        stage1.Params.Seed = int(config.random_seed)

        builder = MILPModelBuilder()
        trip_by_id = problem.trip_by_id()
        dispatch_trip_by_id = problem.dispatch_context.trips_by_id()
        assignment_pairs = builder.enumerate_assignment_pairs(problem)
        arc_pairs = builder.enumerate_arc_pairs(problem, trip_by_id)
        arc_pruning_summary = builder.arc_pruning_summary(problem, trip_by_id)
        vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
        assignment_trip_ids_by_vehicle: Dict[str, List[str]] = {}
        assignment_vehicle_ids_by_trip: Dict[str, List[str]] = {}
        startup_feasible_by_assignment: Dict[Tuple[str, str], bool] = {}
        startup_energy_feasible_by_assignment: Dict[Tuple[str, str], bool] = {}
        startup_energy_precheck_by_assignment: Dict[
            Tuple[str, str], StartupEnergyPrecheck
        ] = {}
        startup_infeasible_trip_ids: Set[str] = set()
        startup_infeasible_vehicle_ids: Set[str] = set()
        startup_energy_infeasible_trip_ids: Set[str] = set()
        startup_energy_infeasible_vehicle_ids: Set[str] = set()
        for vehicle_id, trip_id in assignment_pairs:
            assignment_trip_ids_by_vehicle.setdefault(vehicle_id, []).append(trip_id)
            assignment_vehicle_ids_by_trip.setdefault(trip_id, []).append(vehicle_id)
            startup_precheck = self._startup_energy_precheck(
                problem,
                vehicle_by_id.get(str(vehicle_id)),
                trip_by_id.get(str(trip_id)),
                dispatch_trip_by_id=dispatch_trip_by_id,
            )
            startup_energy_precheck_by_assignment[(vehicle_id, trip_id)] = (
                startup_precheck
            )
            startup_feasible_by_assignment[(vehicle_id, trip_id)] = bool(
                startup_precheck.path_feasible
            )
            startup_energy_feasible_by_assignment[(vehicle_id, trip_id)] = bool(
                startup_precheck.energy_feasible
            )
            if not startup_feasible_by_assignment[(vehicle_id, trip_id)]:
                startup_infeasible_trip_ids.add(str(trip_id))
                startup_infeasible_vehicle_ids.add(str(vehicle_id))
            if not startup_energy_feasible_by_assignment[(vehicle_id, trip_id)]:
                startup_energy_infeasible_trip_ids.add(str(trip_id))
                startup_energy_infeasible_vehicle_ids.add(str(vehicle_id))

        planning_days = max(int(problem.metadata.get("planning_days") or problem.scenario.planning_days or 1), 1)
        slots_per_day = max(1, (24 * 60) // max(problem.scenario.timestep_min, 1))
        trip_day_index_by_trip_id = {
            trip.trip_id: self._trip_day_index(problem, trip.departure_min)
            for trip in problem.trips
        }
        day_indices = sorted(set(range(planning_days)) | set(trip_day_index_by_trip_id.values()))
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

        y: Dict[Tuple[str, str], Any] = {
            (vehicle_id, trip_id): stage1.addVar(
                vtype=GRB.BINARY,
                name=f"y_{vehicle_id}_{trip_id}",
            )
            for vehicle_id, trip_id in assignment_pairs
        }
        x: Dict[Tuple[str, str, str], Any] = {
            (vehicle_id, from_trip_id, to_trip_id): stage1.addVar(
                vtype=GRB.BINARY,
                name=f"x_{vehicle_id}_{from_trip_id}_{to_trip_id}",
            )
            for vehicle_id, from_trip_id, to_trip_id in arc_pairs
        }
        start_arc: Dict[Tuple[str, str], Any] = {
            (vehicle_id, trip_id): stage1.addVar(
                vtype=GRB.BINARY,
                name=f"start_{vehicle_id}_{trip_id}",
            )
            for vehicle_id, trip_id in assignment_pairs
        }
        end_arc: Dict[Tuple[str, str], Any] = {
            (vehicle_id, trip_id): stage1.addVar(
                vtype=GRB.BINARY,
                name=f"end_{vehicle_id}_{trip_id}",
            )
            for vehicle_id, trip_id in assignment_pairs
        }
        used_vehicle: Dict[str, Any] = {
            vehicle.vehicle_id: stage1.addVar(
                vtype=GRB.BINARY,
                name=f"used_{vehicle.vehicle_id}",
            )
            for vehicle in problem.vehicles
        }
        used_vehicle_day: Dict[Tuple[str, int], Any] = {
            (vehicle.vehicle_id, day_idx): stage1.addVar(
                vtype=GRB.BINARY,
                name=f"used_{vehicle.vehicle_id}_d{day_idx}",
            )
            for vehicle in problem.vehicles
            for day_idx in day_indices
        }

        strict_precheck = dict(
            problem.metadata.get("strict_coverage_precheck") or {}
        )
        stage1_vehicle_count_lower_bound = max(
            int(strict_precheck.get("relaxed_vehicle_lower_bound") or 0),
            0,
        )
        stage1_vehicle_count_lower_bound_constraint_count = 0
        if stage1_vehicle_count_lower_bound > 0:
            stage1.addConstr(
                gp.quicksum(used_vehicle_day.values())
                >= stage1_vehicle_count_lower_bound,
                name="stage1_strict_path_cover_vehicle_day_lb",
            )
            stage1_vehicle_count_lower_bound_constraint_count = 1

        for trip in problem.trips:
            assign_terms = [
                y[(vehicle_id, trip.trip_id)]
                for vehicle_id in assignment_vehicle_ids_by_trip.get(trip.trip_id, [])
                if (vehicle_id, trip.trip_id) in y
            ]
            # thesis_mode intentionally has no unserved decision variable.
            stage1.addConstr(gp.quicksum(assign_terms) == 1, name=f"cover_{trip.trip_id}")

        for (vehicle_id, _trip_id), var in y.items():
            stage1.addConstr(var <= used_vehicle[vehicle_id])
        for vehicle in problem.vehicles:
            if not bool(getattr(vehicle, "available", True)):
                stage1.addConstr(used_vehicle[vehicle.vehicle_id] == 0)
        minimum_used_bev_count = max(
            int(problem.metadata.get("minimum_used_bev_count") or 0),
            0,
        )
        available_bev_use_vars = [
            used_vehicle[vehicle.vehicle_id]
            for vehicle in problem.vehicles
            if bool(getattr(vehicle, "available", True))
            and str(getattr(vehicle, "vehicle_type", "") or "").upper() == "BEV"
        ]
        if minimum_used_bev_count > len(available_bev_use_vars):
            raise ValueError(
                "minimum_used_bev_count exceeds available BEV inventory: "
                f"{minimum_used_bev_count} > {len(available_bev_use_vars)}"
            )
        if minimum_used_bev_count > 0:
            stage1.addConstr(
                gp.quicksum(available_bev_use_vars) >= minimum_used_bev_count,
                name="minimum_used_bev_count_policy",
            )

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
                    stage1.addConstr(day_var == 0)
                    continue
                for trip_var in day_trip_vars:
                    stage1.addConstr(trip_var <= day_var)
                stage1.addConstr(day_var <= gp.quicksum(day_trip_vars))
                stage1.addConstr(day_var <= used_vehicle[vehicle_id])
            stage1.addConstr(
                used_vehicle[vehicle_id]
                <= gp.quicksum(
                    used_vehicle_day[(vehicle_id, day_idx)]
                    for day_idx in day_indices
                )
            )

        outgoing_by_node: Dict[Tuple[str, str], List[Any]] = {}
        incoming_by_node: Dict[Tuple[str, str], List[Any]] = {}
        for (vehicle_id, from_trip_id, to_trip_id), var in x.items():
            outgoing_by_node.setdefault((vehicle_id, from_trip_id), []).append(var)
            incoming_by_node.setdefault((vehicle_id, to_trip_id), []).append(var)
        # The node-flow equalities below imply both x[v,i,j] <= y[v,i] and
        # x[v,i,j] <= y[v,j]: every x is nonnegative and belongs to an
        # outgoing/incoming sum equal to y minus a nonnegative boundary arc.
        # Adding the pair explicitly for every arc does not tighten the LP
        # relaxation and created 2 * |x| redundant constraints.
        stage1_redundant_arc_link_constraints_omitted = 2 * len(x)
        for key, var in start_arc.items():
            if not startup_feasible_by_assignment.get(
                key, True
            ) or not startup_energy_feasible_by_assignment.get(key, True):
                stage1.addConstr(var == 0)

        max_start_fragments_per_vehicle = self._safe_positive_int(
            problem.metadata.get("max_start_fragments_per_vehicle"),
            default=1,
        )
        max_end_fragments_per_vehicle = self._safe_positive_int(
            problem.metadata.get("max_end_fragments_per_vehicle"),
            default=1,
        )
        for vehicle in problem.vehicles:
            vehicle_terms_start: List[Any] = []
            vehicle_terms_end: List[Any] = []
            for trip_id in assignment_trip_ids_by_vehicle.get(vehicle.vehicle_id, []):
                key = (vehicle.vehicle_id, trip_id)
                if key not in y:
                    continue
                stage1.addConstr(gp.quicksum(incoming_by_node.get(key, [])) + start_arc[key] == y[key])
                stage1.addConstr(gp.quicksum(outgoing_by_node.get(key, [])) + end_arc[key] == y[key])
                vehicle_terms_start.append(start_arc[key])
                vehicle_terms_end.append(end_arc[key])
            stage1.addConstr(gp.quicksum(vehicle_terms_start) <= max_start_fragments_per_vehicle)
            stage1.addConstr(gp.quicksum(vehicle_terms_end) <= max_end_fragments_per_vehicle)
            for day_idx in day_indices:
                day_trip_ids = [
                    trip_id
                    for trip_id in assignment_trip_ids_by_vehicle.get(vehicle.vehicle_id, [])
                    if int(trip_day_index_by_trip_id.get(trip_id, 0)) == day_idx
                ]
                stage1.addConstr(
                    gp.quicksum(
                        start_arc[(vehicle.vehicle_id, trip_id)]
                        for trip_id in day_trip_ids
                        if (vehicle.vehicle_id, trip_id) in start_arc
                    )
                    <= daily_fragment_limit
                )
                stage1.addConstr(
                    gp.quicksum(
                        end_arc[(vehicle.vehicle_id, trip_id)]
                        for trip_id in day_trip_ids
                        if (vehicle.vehicle_id, trip_id) in end_arc
                    )
                    <= daily_fragment_limit
                )

        stage1_single_path_redundancy_elimination_applied = (
            _single_path_flow_implies_temporal_exclusivity(
                max_start_fragments_per_vehicle=max_start_fragments_per_vehicle,
                max_end_fragments_per_vehicle=max_end_fragments_per_vehicle,
                arc_pairs=arc_pairs,
                trip_by_id=trip_by_id,
            )
        )
        if stage1_single_path_redundancy_elimination_applied:
            fragment_pairwise_depot_reset_constraint_count = 0
            fragment_temporal_occupancy_constraint_count = 0
        else:
            fragment_pairwise_depot_reset_constraint_count = (
                self._add_fragment_pairwise_depot_reset_cuts(
                    stage1,
                    trip_by_id=trip_by_id,
                    vehicles=problem.vehicles,
                    assignment_trip_ids_by_vehicle=assignment_trip_ids_by_vehicle,
                    start_arc=start_arc,
                    end_arc=end_arc,
                    trip_day_index_by_trip_id=trip_day_index_by_trip_id,
                    problem=problem,
                    allow_same_day_depot_cycles=allow_same_day_depot_cycles,
                    fixed_route_band_mode=bool(
                        problem.metadata.get("fixed_route_band_mode", False)
                    ),
                )
            )
            fragment_temporal_occupancy_constraint_count = (
                self._add_fragment_temporal_occupancy_constraints(
                    stage1,
                    grb=GRB,
                    trip_by_id=trip_by_id,
                    vehicles=problem.vehicles,
                    assignment_trip_ids_by_vehicle=assignment_trip_ids_by_vehicle,
                    start_arc=start_arc,
                    end_arc=end_arc,
                    problem=problem,
                )
            )

        overlap_clique_constraint_count = 0
        if not stage1_single_path_redundancy_elimination_applied:
            overlap_cliques = self._build_trip_overlap_cliques(problem)
            for vehicle in problem.vehicles:
                for clique_trip_ids in overlap_cliques:
                    terms = [
                        y[(vehicle.vehicle_id, trip_id)]
                        for trip_id in clique_trip_ids
                        if (vehicle.vehicle_id, trip_id) in y
                    ]
                    if len(terms) > 1:
                        stage1.addConstr(gp.quicksum(terms) <= 1)
                        overlap_clique_constraint_count += 1

        # Stage 1 deliberately does not contain the full time-indexed SOC
        # model.  It must nevertheless reject duties whose total energy need
        # cannot be met even under an optimistic, vehicle-local charging
        # envelope.  Without this necessary condition, Stage 1 can prefer a
        # lower-cost BEV chain that Stage 2 proves infeasible immediately.
        # The envelope only counts potential charge opportunities and ignores
        # charger/grid competition, so it never substitutes for Stage 2.
        stage1_energy_envelope_constraint_count = (
            self._add_stage1_energy_envelope_constraints(
                stage1,
                problem=problem,
                trip_by_id=trip_by_id,
                vehicles=problem.vehicles,
                assignment_trip_ids_by_vehicle=assignment_trip_ids_by_vehicle,
                startup_energy_precheck_by_assignment=(
                    startup_energy_precheck_by_assignment
                ),
                y=y,
                x=x,
                start_arc=start_arc,
                end_arc=end_arc,
                used_vehicle=used_vehicle,
            )
        )
        # The all-day energy envelope above deliberately ignores time order.
        # Add a second, still optimistic relaxation that carries SOC across
        # slots.  It lets a vehicle charge at full power in every non-trip
        # slot regardless of its physical location, charger-port contention,
        # grid capacity, PV, BESS, and deadhead.  Those omissions make it a
        # necessary condition for Stage 2 rather than a duplicate of Stage 2,
        # while preventing Stage 1 from assigning an early sequence that
        # depletes a low-SOC BEV before its first possible recharge.
        stage1_time_indexed_soc_relaxation_enabled = bool(
            problem.metadata.get("stage1_time_indexed_soc_relaxation_enabled", True)
        )
        stage1_time_indexed_soc_relaxation_constraint_count = (
            self._add_stage1_time_indexed_soc_relaxation(
                stage1,
                grb=GRB,
                problem=problem,
                trip_by_id=trip_by_id,
                vehicles=problem.vehicles,
                assignment_trip_ids_by_vehicle=assignment_trip_ids_by_vehicle,
                startup_energy_precheck_by_assignment=(
                    startup_energy_precheck_by_assignment
                ),
                y=y,
                x=x,
                start_arc=start_arc,
                end_arc=end_arc,
                used_vehicle=used_vehicle,
            )
            if stage1_time_indexed_soc_relaxation_enabled
            else 0
        )

        component_flags = normalize_cost_component_flags(
            problem.metadata.get("cost_component_flags")
        )
        stage1_energy_cost_proxy = self._add_stage1_energy_cost_proxy(
            stage1,
            gp=gp,
            grb=GRB,
            problem=problem,
            trip_by_id=trip_by_id,
            vehicles=problem.vehicles,
            assignment_trip_ids_by_vehicle=assignment_trip_ids_by_vehicle,
            startup_energy_precheck_by_assignment=(
                startup_energy_precheck_by_assignment
            ),
            y=y,
            x=x,
            start_arc=start_arc,
            end_arc=end_arc,
            used_vehicle=used_vehicle,
            component_flags=component_flags,
        )
        objective1 = gp.LinExpr(stage1_energy_cost_proxy.objective_expression)
        diesel_price = (
            max(problem.scenario.diesel_price_yen_per_l, 0.0)
            if component_flags.get("fuel_cost", True)
            else 0.0
        )
        co2_price = (
            max(problem.scenario.co2_price_per_kg, 0.0)
            if component_flags.get("co2_cost", True)
            else 0.0
        )
        vehicle_type_by_id = {
            str(item.vehicle_type_id): item for item in problem.vehicle_types
        }

        def _ice_fuel_unit_cost(vehicle: Any) -> float:
            vehicle_type = vehicle_type_by_id.get(str(vehicle.vehicle_type))
            co2_kg_per_l = max(problem.scenario.ice_co2_kg_per_l, 0.0)
            if vehicle_type is not None:
                configured = max(
                    float(vehicle_type.co2_emission_kg_per_l or 0.0),
                    0.0,
                )
                if configured > 0.0:
                    co2_kg_per_l = configured
            return diesel_price + co2_price * co2_kg_per_l

        if diesel_price > 0.0 or co2_price > 0.0:
            for (vehicle_id, trip_id), var in y.items():
                vehicle = vehicle_by_id.get(str(vehicle_id))
                if vehicle is None or str(vehicle.vehicle_type).upper() in {"BEV", "PHEV", "FCEV"}:
                    continue
                objective1 += _ice_fuel_unit_cost(vehicle) * self._trip_fuel_l(problem, vehicle, trip_id) * var
            for (vehicle_id, from_trip_id, to_trip_id), var in x.items():
                vehicle = vehicle_by_id.get(str(vehicle_id))
                if vehicle is None or str(vehicle.vehicle_type).upper() in {"BEV", "PHEV", "FCEV"}:
                    continue
                objective1 += _ice_fuel_unit_cost(vehicle) * self._deadhead_fuel_l(problem, vehicle, from_trip_id, to_trip_id) * var
            for assignment_key, var in start_arc.items():
                vehicle_id, _trip_id = assignment_key
                vehicle = vehicle_by_id.get(str(vehicle_id))
                if vehicle is None or str(vehicle.vehicle_type).upper() in {"BEV", "PHEV", "FCEV"}:
                    continue
                fuel_rate = max(
                    float(vehicle.fuel_consumption_l_per_km or 0.0),
                    0.0,
                )
                startup_precheck = startup_energy_precheck_by_assignment.get(
                    assignment_key
                )
                startup_deadhead_min = int(
                    getattr(startup_precheck, "startup_deadhead_min", 0) or 0
                )
                startup_fuel_l = (
                    self._deadhead_distance_km(
                        problem,
                        startup_deadhead_min,
                    )
                    * fuel_rate
                )
                if startup_fuel_l > 0.0:
                    objective1 += (
                        _ice_fuel_unit_cost(vehicle) * startup_fuel_l * var
                    )
            for assignment_key, var in end_arc.items():
                vehicle_id, trip_id = assignment_key
                vehicle = vehicle_by_id.get(str(vehicle_id))
                trip = trip_by_id.get(str(trip_id))
                if (
                    vehicle is None
                    or trip is None
                    or str(vehicle.vehicle_type).upper()
                    in {"BEV", "PHEV", "FCEV"}
                ):
                    continue
                return_exists, return_deadhead_min = return_deadhead_min_to_home(
                    problem,
                    vehicle,
                    trip,
                )
                if not return_exists or return_deadhead_min <= 0:
                    continue
                fuel_rate = max(
                    float(vehicle.fuel_consumption_l_per_km or 0.0),
                    0.0,
                )
                return_fuel_l = (
                    self._deadhead_distance_km(
                        problem,
                        int(return_deadhead_min),
                    )
                    * fuel_rate
                )
                if return_fuel_l > 0.0:
                    objective1 += (
                        _ice_fuel_unit_cost(vehicle) * return_fuel_l * var
                    )
        if component_flags.get("vehicle_fixed_cost", True):
            for vehicle in problem.vehicles:
                objective1 += float(vehicle.fixed_use_cost_jpy or 0.0) * used_vehicle[vehicle.vehicle_id]
        vehicle_usage_unit_cost = self._safe_nonnegative_float(
            problem.metadata.get("vehicle_usage_cost_jpy_per_used_bus"),
            default=0.0,
        )
        if component_flags.get("vehicle_usage_cost", True) and vehicle_usage_unit_cost > 0.0:
            for var in used_vehicle_day.values():
                objective1 += vehicle_usage_unit_cost * var
        # The strict path-cover precheck certifies a minimum number of vehicle
        # days.  When every remaining objective coefficient is nonnegative,
        # multiplying that count by the vehicle-day usage cost is also a valid
        # objective lower bound even if Gurobi does not finish the root
        # relaxation within the time limit.  Keep this analytical certificate
        # separate from Gurobi's own ObjBound telemetry below.
        fixed_use_costs_are_nonnegative = all(
            float(vehicle.fixed_use_cost_jpy or 0.0) >= 0.0
            for vehicle in problem.vehicles
        )
        stage1_analytical_objective_lower_bound = (
            float(stage1_vehicle_count_lower_bound) * vehicle_usage_unit_cost
            if (
                stage1_vehicle_count_lower_bound > 0
                and component_flags.get("vehicle_usage_cost", True)
                and vehicle_usage_unit_cost > 0.0
                and fixed_use_costs_are_nonnegative
            )
            else None
        )
        stage1_certified_gap_stop_threshold = (
            _best_objective_stop_from_certified_lower_bound(
                stage1_analytical_objective_lower_bound,
                float(config.mip_gap),
            )
        )
        if stage1_certified_gap_stop_threshold is not None:
            stage1.Params.BestObjStop = stage1_certified_gap_stop_threshold
        stage1.setObjective(objective1, GRB.MINIMIZE)
        (
            stage1_warm_start_applied,
            stage1_warm_start_source,
            stage1_warm_start_rejection_reason,
        ) = self._apply_stage1_assignment_warm_start(
            problem,
            enabled=bool(getattr(config, "warm_start", True)),
            preferred_plan=getattr(config, "fixed_assignment", None),
            y=y,
            x=x,
            start_arc=start_arc,
            end_arc=end_arc,
            used_vehicle=used_vehicle,
            used_vehicle_day=used_vehicle_day,
            trip_day_index_by_trip_id=trip_day_index_by_trip_id,
        )
        stage1_pre_optimize_seconds = float(time.perf_counter() - total_started)
        stage1_search_telemetry = _Stage1SearchTelemetry(
            requested_gap_ratio=float(config.mip_gap),
        )

        def _stage1_search_callback(model: Any, where: int) -> None:
            try:
                if where == GRB.Callback.MIPSOL:
                    stage1_search_telemetry.record_incumbent(
                        runtime_sec=model.cbGet(GRB.Callback.RUNTIME),
                        incumbent_objective=model.cbGet(GRB.Callback.MIPSOL_OBJ),
                        best_bound=model.cbGet(GRB.Callback.MIPSOL_OBJBND),
                        explored_node_count=model.cbGet(GRB.Callback.MIPSOL_NODCNT),
                        solution_count=model.cbGet(GRB.Callback.MIPSOL_SOLCNT),
                    )
                elif where == GRB.Callback.MIP:
                    stage1_search_telemetry.record_progress(
                        runtime_sec=model.cbGet(GRB.Callback.RUNTIME),
                        incumbent_objective=model.cbGet(GRB.Callback.MIP_OBJBST),
                        best_bound=model.cbGet(GRB.Callback.MIP_OBJBND),
                        explored_node_count=model.cbGet(GRB.Callback.MIP_NODCNT),
                        solution_count=model.cbGet(GRB.Callback.MIP_SOLCNT),
                    )
            except Exception as exc:  # pragma: no cover - solver callback boundary
                if not stage1_search_telemetry.callback_error:
                    stage1_search_telemetry.callback_error = (
                        f"{type(exc).__name__}: {exc}"
                    )

        stage1.optimize(_stage1_search_callback)

        stage1_status = self._status_name(GRB, stage1.Status)
        stage1_model_variable_count = int(getattr(stage1, "NumVars", 0) or 0)
        stage1_model_constraint_count = int(getattr(stage1, "NumConstrs", 0) or 0)
        stage1_solver_gap = self._model_gap(stage1)
        stage1_solver_bound = self._model_bound(stage1)
        certified_bound_candidates = [
            value
            for value in (
                stage1_solver_bound,
                stage1_analytical_objective_lower_bound,
            )
            if value is not None and math.isfinite(float(value))
        ]
        stage1_bound = (
            max(float(value) for value in certified_bound_candidates)
            if certified_bound_candidates
            else None
        )
        stage1_objective_value = (
            float(getattr(stage1, "ObjVal", 0.0) or 0.0)
            if stage1.SolCount > 0
            else None
        )
        stage1_search_telemetry_result = stage1_search_telemetry.to_dict(
            final_runtime_sec=getattr(stage1, "Runtime", None),
            final_incumbent_objective=stage1_objective_value,
            final_best_bound=stage1_solver_bound,
            final_node_count=getattr(stage1, "NodeCount", None),
            final_solution_count=getattr(stage1, "SolCount", None),
            final_simplex_iteration_count=getattr(stage1, "IterCount", None),
            final_barrier_iteration_count=getattr(stage1, "BarIterCount", None),
        )
        stage1_gap = (
            max(
                float(stage1_objective_value) - float(stage1_bound),
                0.0,
            )
            / max(abs(float(stage1_objective_value)), 1.0e-9)
            if stage1_objective_value is not None and stage1_bound is not None
            else stage1_solver_gap
        )
        stage1_certified_gap_stop_triggered = bool(
            stage1_status == "objective_limit"
            and stage1_gap is not None
            and stage1_gap <= max(float(config.mip_gap), 0.0) + 1.0e-12
        )
        stage1_uses_full_candidate_network = (
            _supports_full_candidate_network_exact_milp(arc_pruning_summary)
        )
        stage1_exact_optimality_certified = _has_exact_mip_optimality_certificate(
            stage1_status,
            stage1_gap,
        )
        assignment_global_optimality = bool(
            stage1_exact_optimality_certified
            and stage1_uses_full_candidate_network
        )
        assignment_global_optimality_scope = (
            "full_candidate_network_stage1_assignment_objective"
        )
        stage1_energy_cost_proxy_result = (
            self._stage1_energy_cost_proxy_result(stage1_energy_cost_proxy)
            if stage1.SolCount > 0
            else {}
        )
        if stage1.SolCount <= 0:
            empty = AssignmentPlan(
                duties=(),
                served_trip_ids=(),
                unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips)),
                metadata={
                    "source": "milp_gurobi_two_stage",
                    "status": stage1_status,
                    "thesis_mode": True,
                    "optimization_structure": "two_stage",
                    "stage1_solver_status": stage1_status,
                    "stage2_solver_status": "not_run",
                    "stage1_has_feasible_incumbent": False,
                    "assignment_solution_method": (
                        "full_candidate_network_stage1_milp"
                    ),
                    "assignment_global_optimality": False,
                    "stage1_exact_optimality_certified": False,
                    "assignment_global_optimality_scope": (
                        assignment_global_optimality_scope
                    ),
                    "assignment_certified_mip_gap_ratio": stage1_gap,
                    "full_network_global_optimality": False,
                    "stage1_objective": None,
                    "stage1_best_bound": stage1_bound,
                    "stage1_solver_best_bound": stage1_solver_bound,
                    "stage1_solver_mip_gap_ratio": stage1_solver_gap,
                    "stage1_analytical_objective_lower_bound": (
                        stage1_analytical_objective_lower_bound
                    ),
                    "stage1_analytical_objective_lower_bound_semantics": (
                        "strict_path_cover_vehicle_day_count_times_nonnegative_"
                        "vehicle_usage_cost"
                    ),
                    "stage1_certified_gap_stop_threshold": (
                        stage1_certified_gap_stop_threshold
                    ),
                    "stage1_certified_gap_stop_triggered": (
                        stage1_certified_gap_stop_triggered
                    ),
                    "stage1_mip_gap_ratio": stage1_gap,
                    "stage1_runtime_seconds": float(time.perf_counter() - total_started),
                    "stage1_pre_optimize_seconds": stage1_pre_optimize_seconds,
                    "stage1_model_variable_count": stage1_model_variable_count,
                    "stage1_model_constraint_count": stage1_model_constraint_count,
                    "stage1_search_telemetry": stage1_search_telemetry_result,
                    "stage2_has_feasible_incumbent": False,
                    "stage2_objective": None,
                    "stage2_best_bound": None,
                    "stage2_mip_gap_ratio": None,
                    "stage2_runtime_seconds": None,
                    "stage1_feasible": False,
                    "stage2_feasible": False,
                    "supports_two_stage_milp": False,
                    "supports_integrated_exact_milp": False,
                    "unserved_variable_created": False,
                    "research_kpi_eligible": False,
                    "startup_infeasible_assignment_count": len(startup_infeasible_trip_ids),
                    "startup_infeasible_trip_ids": tuple(sorted(startup_infeasible_trip_ids)),
                    "startup_infeasible_vehicle_ids": tuple(sorted(startup_infeasible_vehicle_ids)),
                    "startup_energy_infeasible_trip_count": len(
                        startup_energy_infeasible_trip_ids
                    ),
                    "startup_energy_infeasible_trip_ids": tuple(
                        sorted(startup_energy_infeasible_trip_ids)
                    ),
                    "startup_energy_infeasible_vehicle_ids": tuple(
                        sorted(startup_energy_infeasible_vehicle_ids)
                    ),
                    "arc_pruning_summary": arc_pruning_summary,
                    "stage1_redundant_arc_link_constraints_omitted": (
                        stage1_redundant_arc_link_constraints_omitted
                    ),
                    "fragment_temporal_occupancy_constraint_count": (
                        fragment_temporal_occupancy_constraint_count
                    ),
                    "fragment_pairwise_depot_reset_constraint_count": (
                        fragment_pairwise_depot_reset_constraint_count
                    ),
                    "overlap_clique_constraint_count": (
                        overlap_clique_constraint_count
                    ),
                    "stage1_single_path_redundancy_elimination_applied": (
                        stage1_single_path_redundancy_elimination_applied
                    ),
                    "stage1_energy_envelope_constraint_count": (
                        stage1_energy_envelope_constraint_count
                    ),
                    "stage1_vehicle_count_lower_bound": (
                        stage1_vehicle_count_lower_bound
                    ),
                    "stage1_vehicle_count_lower_bound_constraint_count": (
                        stage1_vehicle_count_lower_bound_constraint_count
                    ),
                    "stage1_vehicle_count_lower_bound_semantics": (
                        "relaxed_dispatch_feasible_minimum_path_cover_vehicle_day_lb"
                    ),
                    "minimum_used_bev_count": minimum_used_bev_count,
                    "minimum_used_bev_count_policy_enabled": (
                        minimum_used_bev_count > 0
                    ),
                    "stage1_energy_envelope_semantics": (
                        "optimistic_vehicle_local_necessary_condition"
                    ),
                    "stage1_time_indexed_soc_relaxation_constraint_count": (
                        stage1_time_indexed_soc_relaxation_constraint_count
                    ),
                    "stage1_time_indexed_soc_relaxation_enabled": (
                        stage1_time_indexed_soc_relaxation_enabled
                    ),
                    "stage1_time_indexed_soc_relaxation_semantics": (
                        "location_aware_cumulative_soc_with_single_vehicle_slot_"
                        "charge_cap_necessary_condition"
                    ),
                    "stage1_energy_cost_proxy_configuration": dict(
                        stage1_energy_cost_proxy.configuration
                    ),
                    "stage1_ice_boundary_fuel_cost_terms_enabled": True,
                    "stage1_ice_boundary_fuel_cost_semantics": (
                        "startup_and_terminal_return_deadhead_fuel_and_co2"
                    ),
                    "stage1_energy_cost_proxy_weather_input": dict(
                        stage1_energy_cost_proxy.weather_input
                    ),
                    "stage1_energy_cost_proxy_result": {},
                    "stage1_warm_start_applied": stage1_warm_start_applied,
                    "stage1_warm_start_source": stage1_warm_start_source,
                    "stage1_warm_start_rejection_reason": (
                        stage1_warm_start_rejection_reason
                    ),
                },
            )
            return (
                MILPSolverOutcome(
                    solver_status=stage1_status,
                    used_backend="gurobi_two_stage",
                    supports_exact_milp=_supports_full_candidate_network_exact_milp(
                        arc_pruning_summary
                    ),
                    has_feasible_incumbent=False,
                    incumbent_count=0,
                    best_bound=stage1_bound,
                    final_gap=stage1_gap,
                    runtime_sec=float(time.perf_counter() - total_started),
                    warm_start_applied=stage1_warm_start_applied,
                    warm_start_source=stage1_warm_start_source,
                ),
                empty,
            )

        duties, served_trip_ids, duty_vehicle_map = self._build_vehicle_duties_from_solution(
            problem=problem,
            trip_by_id=trip_by_id,
            dispatch_trip_by_id=dispatch_trip_by_id,
            y=y,
            x=x,
            start_arc=start_arc,
        )
        served_set = set(served_trip_ids)
        stage1_plan = AssignmentPlan(
            duties=tuple(duties),
            served_trip_ids=tuple(sorted(served_set)),
            unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips if trip.trip_id not in served_set)),
            metadata={
                "source": "milp_gurobi_two_stage",
                "status": stage1_status,
                "thesis_mode": True,
                "optimization_structure": "two_stage",
                "stage1_solver_status": stage1_status,
                "stage1_has_feasible_incumbent": True,
                "assignment_solution_method": (
                    "full_candidate_network_stage1_milp"
                ),
                "assignment_global_optimality": assignment_global_optimality,
                "stage1_exact_optimality_certified": (
                    stage1_exact_optimality_certified
                ),
                "assignment_global_optimality_scope": (
                    assignment_global_optimality_scope
                ),
                "assignment_certified_mip_gap_ratio": stage1_gap,
                # Phase 3 optimizes assignment and charging sequentially, not
                # as one integrated total-cost model.
                "full_network_global_optimality": False,
                "stage1_objective": stage1_objective_value,
                "stage1_best_bound": stage1_bound,
                "stage1_solver_best_bound": stage1_solver_bound,
                "stage1_solver_mip_gap_ratio": stage1_solver_gap,
                "stage1_analytical_objective_lower_bound": (
                    stage1_analytical_objective_lower_bound
                ),
                "stage1_analytical_objective_lower_bound_semantics": (
                    "strict_path_cover_vehicle_day_count_times_nonnegative_"
                    "vehicle_usage_cost"
                ),
                "stage1_certified_gap_stop_threshold": (
                    stage1_certified_gap_stop_threshold
                ),
                "stage1_certified_gap_stop_triggered": (
                    stage1_certified_gap_stop_triggered
                ),
                "stage1_mip_gap_ratio": stage1_gap,
                "stage1_runtime_seconds": float(
                    getattr(stage1, "Runtime", 0.0) or 0.0
                ),
                "stage1_pre_optimize_seconds": stage1_pre_optimize_seconds,
                "stage1_model_variable_count": stage1_model_variable_count,
                "stage1_model_constraint_count": stage1_model_constraint_count,
                "stage1_search_telemetry": stage1_search_telemetry_result,
                "stage1_time_limit_sec_effective": stage_time_limit,
                "unserved_variable_created": False,
                "duty_vehicle_map": duty_vehicle_map,
                "horizon_start": str(problem.scenario.horizon_start or "00:00"),
                "timestep_min": int(problem.scenario.timestep_min),
                "startup_infeasible_assignment_count": len(startup_infeasible_trip_ids),
                "startup_infeasible_trip_ids": tuple(sorted(startup_infeasible_trip_ids)),
                "startup_infeasible_vehicle_ids": tuple(sorted(startup_infeasible_vehicle_ids)),
                "startup_energy_infeasible_trip_count": len(
                    startup_energy_infeasible_trip_ids
                ),
                "startup_energy_infeasible_trip_ids": tuple(
                    sorted(startup_energy_infeasible_trip_ids)
                ),
                "startup_energy_infeasible_vehicle_ids": tuple(
                    sorted(startup_energy_infeasible_vehicle_ids)
                ),
                "arc_pruning_summary": arc_pruning_summary,
                "stage1_redundant_arc_link_constraints_omitted": (
                    stage1_redundant_arc_link_constraints_omitted
                ),
                "fragment_temporal_occupancy_constraint_count": (
                    fragment_temporal_occupancy_constraint_count
                ),
                "fragment_pairwise_depot_reset_constraint_count": (
                    fragment_pairwise_depot_reset_constraint_count
                ),
                "overlap_clique_constraint_count": (
                    overlap_clique_constraint_count
                ),
                "stage1_single_path_redundancy_elimination_applied": (
                    stage1_single_path_redundancy_elimination_applied
                ),
                "stage1_energy_envelope_constraint_count": (
                    stage1_energy_envelope_constraint_count
                ),
                "stage1_vehicle_count_lower_bound": (
                    stage1_vehicle_count_lower_bound
                ),
                "stage1_vehicle_count_lower_bound_constraint_count": (
                    stage1_vehicle_count_lower_bound_constraint_count
                ),
                "stage1_vehicle_count_lower_bound_semantics": (
                    "relaxed_dispatch_feasible_minimum_path_cover_vehicle_day_lb"
                ),
                "minimum_used_bev_count": minimum_used_bev_count,
                "minimum_used_bev_count_policy_enabled": (
                    minimum_used_bev_count > 0
                ),
                "stage1_energy_envelope_semantics": (
                    "optimistic_vehicle_local_necessary_condition"
                ),
                "stage1_time_indexed_soc_relaxation_constraint_count": (
                    stage1_time_indexed_soc_relaxation_constraint_count
                ),
                "stage1_time_indexed_soc_relaxation_enabled": (
                    stage1_time_indexed_soc_relaxation_enabled
                ),
                "stage1_time_indexed_soc_relaxation_semantics": (
                    "location_aware_cumulative_soc_with_single_vehicle_slot_"
                    "charge_cap_necessary_condition"
                ),
                "stage1_energy_cost_proxy_configuration": dict(
                    stage1_energy_cost_proxy.configuration
                ),
                "stage1_ice_boundary_fuel_cost_terms_enabled": True,
                "stage1_ice_boundary_fuel_cost_semantics": (
                    "startup_and_terminal_return_deadhead_fuel_and_co2"
                ),
                "stage1_energy_cost_proxy_weather_input": dict(
                    stage1_energy_cost_proxy.weather_input
                ),
                "stage1_energy_cost_proxy_result": (
                    stage1_energy_cost_proxy_result
                ),
                "stage1_warm_start_applied": stage1_warm_start_applied,
                "stage1_warm_start_source": stage1_warm_start_source,
                "stage1_warm_start_rejection_reason": (
                    stage1_warm_start_rejection_reason
                ),
            },
        )

        if not stage2_enabled:
            stage1_runtime_sec_value = float(getattr(stage1, "Runtime", 0.0) or 0.0)
            stage1_outcome = self._build_stage1_outcome(
                stage1_status=stage1_status,
                stage1_gap=stage1_gap,
                stage1_bound=stage1_bound,
                stage1_runtime_sec=stage1_runtime_sec_value,
                supports_exact_milp=False,
                warm_start_applied=stage1_warm_start_applied,
                warm_start_source=stage1_warm_start_source,
            )
            return stage1_outcome, stage1_plan

        stage2_outcome, final_plan = self._solve_thesis_stage2_charging_dispatch(
            problem,
            config,
            stage1_plan,
            stage1_status=stage1_status,
            stage1_gap=stage1_gap,
            stage1_bound=stage1_bound,
            stage1_objective_value=stage1_objective_value,
            stage1_runtime_sec=float(getattr(stage1, "Runtime", 0.0) or 0.0),
            slots_per_day=slots_per_day,
        )
        return stage2_outcome, final_plan

    def _build_stage1_outcome(
        self,
        *,
        stage1_status: str,
        stage1_gap: Optional[float],
        stage1_bound: Optional[float],
        stage1_runtime_sec: float,
        supports_exact_milp: bool = False,
        fallback_reason: str = "",
        warm_start_applied: bool = False,
        warm_start_source: str = "",
    ) -> MILPSolverOutcome:
        """Construct a MILPSolverOutcome for Stage 1-only Phase 2 runs."""
        return MILPSolverOutcome(
            solver_status="phase2_assignment_feasible"
            if stage1_status == "optimal"
            else stage1_status,
            used_backend=self.backend_name,
            supports_exact_milp=supports_exact_milp,
            has_feasible_incumbent=stage1_status in {
                "optimal",
                "feasible",
                "time_limit",
                "objective_limit",
            },
            incumbent_count=(
                1
                if stage1_status
                in {"optimal", "feasible", "time_limit", "objective_limit"}
                else 0
            ),
            best_bound=stage1_bound,
            final_gap=stage1_gap,
            runtime_sec=stage1_runtime_sec,
            fallback_reason=fallback_reason,
            warm_start_applied=warm_start_applied,
            warm_start_source=warm_start_source,
        )

    def _solve_thesis_stage2_charging_dispatch(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        stage1_plan: AssignmentPlan,
        *,
        stage1_status: str,
        stage1_gap: Optional[float],
        stage1_bound: Optional[float],
        stage1_objective_value: Optional[float],
        stage1_runtime_sec: float,
        slots_per_day: int,
    ) -> Tuple[MILPSolverOutcome, AssignmentPlan]:
        gp, GRB = ensure_gurobi()
        started = time.perf_counter()
        component_flags = normalize_cost_component_flags(
            problem.metadata.get("cost_component_flags")
        )
        minimum_used_bev_count = max(
            int(problem.metadata.get("minimum_used_bev_count") or 0),
            0,
        )
        raw_arc_pruning_summary = (stage1_plan.metadata or {}).get(
            "arc_pruning_summary"
        )
        arc_pruning_summary = (
            dict(raw_arc_pruning_summary)
            if isinstance(raw_arc_pruning_summary, Mapping)
            else {}
        )
        slot_indices = list(
            _stage2_slot_indices(
                problem,
                config,
                sorted({slot.slot_index for slot in problem.price_slots}),
            )
        )
        timestep_h = max(problem.scenario.timestep_min, 1) / 60.0
        rolling_policy = str(
            getattr(config, "rolling_horizon_policy", "") or ""
        ).strip().lower()
        is_remaining_day_reoptimization = (
            rolling_policy == ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT
        )
        rolling_start_abs_min = (
            slot_absolute_min(problem, slot_indices[0])
            if is_remaining_day_reoptimization and slot_indices
            else None
        )
        vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
        bev_vehicle_ids = {
            str(vehicle.vehicle_id)
            for vehicle in problem.vehicles
            if str(vehicle.vehicle_type).upper() in {"BEV", "PHEV", "FCEV"}
        }
        assigned_paths = stage1_plan.vehicle_paths()
        assigned_bev_ids = sorted(set(assigned_paths).intersection(bev_vehicle_ids))
        if not slot_indices or not assigned_bev_ids:
            metadata = {
                **dict(stage1_plan.metadata or {}),
                "stage1_solver_status": stage1_status,
                "stage1_has_feasible_incumbent": True,
                "stage1_objective": stage1_objective_value,
                "stage1_best_bound": stage1_bound,
                "stage1_mip_gap_ratio": stage1_gap,
                "stage1_runtime_seconds": stage1_runtime_sec,
                "stage1_time_limit_sec_effective": (
                    0
                    if stage1_status == "phase1_fixed_assignment"
                    else _resolved_stage_time_limit_sec(config, stage=1)
                ),
                "stage2_solver_status": "not_required",
                "stage2_has_feasible_incumbent": True,
                "stage2_objective": None,
                "stage2_best_bound": stage1_bound,
                "stage2_mip_gap_ratio": None,
                "stage2_runtime_seconds": 0.0,
                "stage2_time_limit_sec_effective": _resolved_stage_time_limit_sec(
                    config, stage=2
                ),
                "rolling_horizon_policy": rolling_policy,
                "rolling_start_slot_index": (
                    slot_indices[0] if is_remaining_day_reoptimization and slot_indices else None
                ),
                "rolling_execution_minutes": getattr(
                    config, "rolling_execution_minutes", None
                ),
                "stage1_feasible": True,
                "stage2_feasible": True,
                "supports_two_stage_milp": True,
                "supports_integrated_exact_milp": False,
                "stage2_reason": "no_ev_charging_dispatch_required",
                "stage1_mip_gap": stage1_gap,
                "stage1_objective_value": stage1_objective_value,
                "stage2_mip_gap": None,
                "stage2_objective_value": None,
                "minimum_used_bev_count": minimum_used_bev_count,
                "minimum_used_bev_count_policy_enabled": (
                    minimum_used_bev_count > 0
                ),
                "solver_objective_matches_accounting_total": False,
                "objective_semantics": "fixed_assignment_energy_dispatch_not_global_total_cost",
                "source_provenance_exact": True,
                "vehicle_source_provenance_exact": False,
                "vehicle_source_allocation_policy": "not_required_no_ev_charging",
                "derived_source_split": False,
                # Phase 3 establishes a feasible dispatch under fixed Stage 1
                # assignments. Its accounting total is not a globally
                # minimized total-cost KPI; the engine determines final
                # feasibility acceptance separately.
                "research_kpi_eligible": False,
                "research_cost_kpi_eligible": False,
                "postsolve_repair_allowed": False,
            }
            plan = replace(stage1_plan, metadata=metadata)
            return (
                MILPSolverOutcome(
                    solver_status="optimal" if stage1_status == "optimal" else "feasible",
                    used_backend="gurobi_two_stage",
                    supports_exact_milp=_supports_full_candidate_network_exact_milp(
                        arc_pruning_summary
                    ),
                    has_feasible_incumbent=True,
                    incumbent_count=1,
                    best_bound=stage1_bound,
                    final_gap=stage1_gap,
                    runtime_sec=stage1_runtime_sec,
                    warm_start_applied=bool(
                        metadata.get("stage1_warm_start_applied", False)
                    ),
                    warm_start_source=str(
                        metadata.get("stage1_warm_start_source") or ""
                    ),
                ),
                plan,
            )

        stage2 = gp.Model("thesis_stage2_charging_dispatch")
        stage2.Params.OutputFlag = 0
        stage2.Params.TimeLimit = _resolved_stage_time_limit_sec(config, stage=2)
        stage2.Params.MIPGap = max(float(config.mip_gap), 0.0)
        stage2.Params.Seed = int(config.random_seed)

        trip_by_id = problem.trip_by_id()
        dispatch_trip_by_id = problem.dispatch_context.trips_by_id()
        c_var: Dict[Tuple[str, int], Any] = {}
        charge_on_var: Dict[Tuple[str, int], Any] = {}
        physical_charger_assignment_var: Dict[Tuple[str, str, int], Any] = {}
        physical_charger_power_var: Dict[Tuple[str, str, int], Any] = {}
        physical_charger_metadata: Dict[str, Any] = {}
        s_var: Dict[Tuple[str, int], Any] = {}
        g2vehicle_var: Dict[Tuple[str, int], Any] = {}
        pv2vehicle_var: Dict[Tuple[str, int], Any] = {}
        bess2vehicle_var: Dict[Tuple[str, int], Any] = {}
        g2bus_var: Dict[Tuple[str, int], Any] = {}
        pv2bus_var: Dict[Tuple[str, int], Any] = {}
        g2bess_var: Dict[Tuple[str, int], Any] = {}
        pv2bess_var: Dict[Tuple[str, int], Any] = {}
        bess2bus_var: Dict[Tuple[str, int], Any] = {}
        pv_curt_var: Dict[Tuple[str, int], Any] = {}
        grid_import_var: Dict[Tuple[str, int], Any] = {}
        p_avg_depot_var: Dict[Tuple[str, int], Any] = {}
        bess_soc_var: Dict[Tuple[str, int], Any] = {}
        bess_charge_mode_var: Dict[Tuple[str, int], Any] = {}
        bess_discharge_mode_var: Dict[Tuple[str, int], Any] = {}
        w_on_depot_var: Dict[str, Any] = {}
        w_off_depot_var: Dict[str, Any] = {}
        w_on_var = None
        w_off_var = None

        trip_load_by_vehicle_slot: Dict[Tuple[str, int], float] = {}
        terminal_out_of_horizon_load_by_vehicle: Dict[str, float] = {}
        active_slot_by_vehicle: Dict[str, Set[int]] = {vehicle_id: set() for vehicle_id in assigned_bev_ids}
        deadhead_active_slot_by_vehicle: Dict[str, Set[int]] = {
            vehicle_id: set() for vehicle_id in assigned_bev_ids
        }
        deadhead_energy_before_trip: Dict[Tuple[str, str], float] = {}
        allowed_charge_slots_by_vehicle: Dict[str, Set[int]] = {vehicle_id: set() for vehicle_id in assigned_bev_ids}
        final_trip_by_vehicle_day: Dict[Tuple[str, int], ProblemTrip] = {}
        first_trip_id_by_vehicle: Dict[str, str] = {}
        startup_precheck_by_vehicle: Dict[str, StartupEnergyPrecheck] = {}
        for vehicle_id, trip_ids in assigned_paths.items():
            candidate_trips = [trip_by_id[trip_id] for trip_id in trip_ids if trip_id in trip_by_id]
            if candidate_trips:
                first_trip = min(
                    candidate_trips,
                    key=lambda trip: self._trip_service_sort_key(problem, trip),
                )
                first_trip_id_by_vehicle[vehicle_id] = first_trip.trip_id
                startup_precheck_by_vehicle[vehicle_id] = self._startup_energy_precheck(
                    problem,
                    vehicle_by_id.get(vehicle_id),
                    first_trip,
                    dispatch_trip_by_id=dispatch_trip_by_id,
                )
        pre_window_min = self._safe_nonnegative_float(
            problem.metadata.get("home_depot_charge_pre_window_min"),
            default=float(max(problem.scenario.timestep_min, 1)) * 2.0,
        )
        post_window_min = self._safe_nonnegative_float(
            problem.metadata.get("home_depot_charge_post_window_min"),
            default=float(max(problem.scenario.timestep_min, 1)) * 2.0,
        )
        operation_start_min = self._operation_start_min(problem)
        operation_end_min = self._operation_end_min(problem)
        planning_days = max(int(problem.metadata.get("planning_days") or problem.scenario.planning_days or 1), 1)

        for duty in stage1_plan.duties:
            vehicle_id = str(stage1_plan.vehicle_id_for_duty(duty.duty_id))
            if vehicle_id not in assigned_bev_ids:
                continue
            vehicle = vehicle_by_id.get(vehicle_id)
            if vehicle is None:
                continue
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "depot_default")
            previous_trip_id: Optional[str] = None
            for leg_index, leg in enumerate(duty.legs):
                trip = trip_by_id.get(str(leg.trip.trip_id))
                if trip is None:
                    continue
                day_key = (vehicle_id, self._trip_day_index(problem, trip.departure_min))
                previous_day_final = final_trip_by_vehicle_day.get(day_key)
                if previous_day_final is None or self._trip_service_sort_key(
                    problem, trip
                ) > self._trip_service_sort_key(problem, previous_day_final):
                    final_trip_by_vehicle_day[day_key] = trip
                for slot_idx in slot_indices:
                    if self._trip_active_in_slot(problem, trip.departure_min, trip.arrival_min, slot_idx):
                        active_slot_by_vehicle[vehicle_id].add(slot_idx)
                        trip_load_by_vehicle_slot[(vehicle_id, slot_idx)] = trip_load_by_vehicle_slot.get((vehicle_id, slot_idx), 0.0) + self._trip_energy_kwh(problem, vehicle, trip.trip_id) * self._trip_slot_energy_fraction(
                            problem,
                            trip.departure_min,
                            trip.arrival_min,
                            slot_idx,
                        )
                allocated_fraction = sum(
                    self._trip_slot_energy_fraction(
                        problem,
                        trip.departure_min,
                        trip.arrival_min,
                        slot_idx,
                    )
                    for slot_idx in slot_indices
                )
                if is_remaining_day_reoptimization and rolling_start_abs_min is not None:
                    departure_abs = self._service_minute(
                        problem, int(trip.departure_min)
                    )
                    arrival_abs = self._trip_service_arrival_min(problem, trip)
                    duration_min = max(arrival_abs - departure_abs, 1)
                    remaining_fraction = max(
                        arrival_abs - max(departure_abs, rolling_start_abs_min),
                        0,
                    ) / duration_min
                    unallocated_fraction = max(
                        remaining_fraction - allocated_fraction,
                        0.0,
                    )
                else:
                    unallocated_fraction = max(1.0 - allocated_fraction, 0.0)
                if unallocated_fraction > 1.0e-9:
                    terminal_out_of_horizon_load_by_vehicle[vehicle_id] = (
                        terminal_out_of_horizon_load_by_vehicle.get(vehicle_id, 0.0)
                        + self._trip_energy_kwh(problem, vehicle, trip.trip_id)
                        * unallocated_fraction
                    )
                if previous_trip_id is not None:
                    previous_trip = trip_by_id.get(previous_trip_id)
                    deadhead_slot = self._slot_index(problem, trip.departure_min)
                    deadhead_energy_kwh = self._deadhead_energy_kwh(
                        problem,
                        vehicle,
                        previous_trip_id,
                        trip.trip_id,
                    )
                    deadhead_fraction = 1.0
                    if (
                        is_remaining_day_reoptimization
                        and rolling_start_abs_min is not None
                        and previous_trip is not None
                    ):
                        deadhead_min = self._connection_deadhead_min(
                            problem, previous_trip, trip
                        )
                        deadhead_start, deadhead_end = self._connection_deadhead_interval(
                            problem,
                            vehicle,
                            previous_trip,
                            trip,
                            deadhead_min=deadhead_min,
                        )
                        deadhead_fraction = _remaining_posted_transition_fraction(
                            event_end_min=deadhead_end,
                            rolling_start_abs_min=rolling_start_abs_min,
                        )
                    remaining_deadhead_energy_kwh = (
                        deadhead_energy_kwh * deadhead_fraction
                    )
                    trip_load_by_vehicle_slot[(vehicle_id, deadhead_slot)] = (
                        trip_load_by_vehicle_slot.get((vehicle_id, deadhead_slot), 0.0)
                        + remaining_deadhead_energy_kwh
                    )
                    deadhead_energy_before_trip[(vehicle_id, trip.trip_id)] = (
                        remaining_deadhead_energy_kwh
                    )
                    if previous_trip is not None:
                        deadhead_min = self._connection_deadhead_min(
                            problem, previous_trip, trip
                        )
                        residence_interval = self._home_depot_residence_interval(
                            problem,
                            vehicle,
                            previous_trip,
                            trip,
                            deadhead_min=deadhead_min,
                        )
                        if residence_interval is not None:
                            allowed_charge_slots_by_vehicle[vehicle_id].update(
                                self._slot_indices_for_interval(
                                    problem,
                                    residence_interval[0],
                                    residence_interval[1],
                                )
                            )
                        if deadhead_min > 0:
                            deadhead_interval = self._connection_deadhead_interval(
                                problem,
                                vehicle,
                                previous_trip,
                                trip,
                                deadhead_min=deadhead_min,
                            )
                            deadhead_active_slot_by_vehicle[vehicle_id].update(
                                self._slot_indices_for_interval(
                                    problem,
                                    deadhead_interval[0],
                                    deadhead_interval[1],
                                )
                            )
                elif str(trip.trip_id) == first_trip_id_by_vehicle.get(vehicle_id):
                    # Only the first Stage-1 trip for a vehicle may use the
                    # initial at-home assumption.  A later duty fragment has
                    # no implied vehicle repositioning, so treating its first
                    # leg as another depot start would create fictitious
                    # charging availability.
                    first_window_start = self._horizon_start_min(problem)
                    startup_precheck = startup_precheck_by_vehicle[vehicle_id]
                    first_departure_min = self._service_minute(
                        problem, int(trip.departure_min)
                    )
                    leave_depot_min = first_departure_min - int(
                        startup_precheck.startup_deadhead_min
                    )
                    allowed_charge_slots_by_vehicle[vehicle_id].update(
                        self._slot_indices_for_interval(
                            problem,
                            first_window_start,
                            max(leave_depot_min, first_window_start + 1),
                        )
                    )
                    if startup_precheck.startup_deadhead_min > 0:
                        deadhead_active_slot_by_vehicle[vehicle_id].update(
                            self._slot_indices_for_interval(
                                problem,
                                leave_depot_min,
                                first_departure_min,
                            )
                        )
                    departure_slot = self._slot_index(problem, trip.departure_min)
                    startup_energy_kwh = startup_precheck.startup_deadhead_energy_kwh
                    if (
                        is_remaining_day_reoptimization
                        and rolling_start_abs_min is not None
                        and first_departure_min > leave_depot_min
                    ):
                        startup_energy_kwh *= _remaining_posted_transition_fraction(
                            event_end_min=first_departure_min,
                            rolling_start_abs_min=rolling_start_abs_min,
                        )
                    trip_load_by_vehicle_slot[(vehicle_id, departure_slot)] = (
                        trip_load_by_vehicle_slot.get((vehicle_id, departure_slot), 0.0)
                        + startup_energy_kwh
                    )
                    deadhead_energy_before_trip[(vehicle_id, trip.trip_id)] = (
                        startup_energy_kwh
                    )
                if str(trip.origin) == home_depot_id or str(trip.destination) == home_depot_id:
                    allowed_charge_slots_by_vehicle[vehicle_id].update(
                        self._collect_home_depot_window_slots(
                            problem,
                            trip,
                            home_depot_id=home_depot_id,
                            pre_window_min=pre_window_min,
                            post_window_min=post_window_min,
                        )
                    )
                if leg_index == len(duty.legs) - 1:
                    return_exists, return_deadhead_min = return_deadhead_min_to_home(problem, vehicle, trip)
                    if return_exists:
                        return_slot = slot_index_ceil(
                            problem,
                            self._trip_service_arrival_min(problem, trip)
                            + int(return_deadhead_min),
                        )
                        return_kwh = return_deadhead_energy_kwh(problem, vehicle, trip)
                        return_transition_slot = _transition_slot_ending_at_event(
                            slot_indices,
                            return_slot,
                        )
                        return_start_min = self._trip_service_arrival_min(problem, trip)
                        return_end_min = return_start_min + int(return_deadhead_min)
                        if (
                            is_remaining_day_reoptimization
                            and rolling_start_abs_min is not None
                        ):
                            return_kwh *= _remaining_posted_transition_fraction(
                                event_end_min=return_end_min,
                                rolling_start_abs_min=rolling_start_abs_min,
                            )
                        if return_transition_slot is None and return_kwh > 1.0e-9:
                            terminal_out_of_horizon_load_by_vehicle[vehicle_id] = (
                                terminal_out_of_horizon_load_by_vehicle.get(vehicle_id, 0.0)
                                + max(return_kwh, 0.0)
                            )
                        elif return_transition_slot is not None:
                            trip_load_by_vehicle_slot[
                                (vehicle_id, return_transition_slot)
                            ] = (
                                trip_load_by_vehicle_slot.get(
                                    (vehicle_id, return_transition_slot),
                                    0.0,
                                )
                                + max(return_kwh, 0.0)
                            )
                        allowed_charge_slots_by_vehicle[vehicle_id].update(
                            self._collect_post_return_target_slots(
                                problem,
                                trip=trip,
                                day_idx=self._trip_day_index(problem, trip.departure_min),
                                return_deadhead_min=int(return_deadhead_min),
                            )
                        )
                previous_trip_id = trip.trip_id

        # An overnight charger is physically reachable only after the final
        # Stage-1 trip of that vehicle/day has returned to its home depot.
        # Do not infer this from ``used_vehicle``: Stage 1 does not otherwise
        # force each daily path to end at the depot when no terminal target is
        # configured.
        for (vehicle_id, day_idx), final_trip in final_trip_by_vehicle_day.items():
            if day_idx >= planning_days - 1:
                continue
            vehicle = vehicle_by_id.get(vehicle_id)
            if vehicle is None:
                continue
            return_exists, return_deadhead_min = return_deadhead_min_to_home(
                problem,
                vehicle,
                final_trip,
            )
            if not return_exists:
                continue
            home_arrival_min = self._trip_service_arrival_min(
                problem, final_trip
            ) + int(return_deadhead_min)
            allowed_charge_slots_by_vehicle[vehicle_id].update(
                self._collect_overnight_home_depot_slots(
                    problem,
                    day_idx=day_idx,
                    operation_start_min=operation_start_min,
                    operation_end_min=operation_end_min,
                    earliest_home_arrival_min=home_arrival_min,
                )
            )

        for vehicle_id in assigned_bev_ids:
            vehicle = vehicle_by_id[vehicle_id]
            cap = max(float(vehicle.battery_capacity_kwh or 300.0), 1.0)
            reserve = vehicle.reserve_soc
            soc_min = 0.15 * cap if reserve is None else (float(reserve) * cap if float(reserve) <= 1.0 else float(reserve))
            charge_max_kw = self._vehicle_charge_power_max_kw(problem, vehicle)
            if problem.chargers:
                max_charger_kw = max(float(charger.power_kw or 0.0) for charger in problem.chargers)
                if max_charger_kw > 0.0:
                    charge_max_kw = min(charge_max_kw, max_charger_kw)
            initial_soc = vehicle.initial_soc
            initial_kwh = 0.8 * cap if initial_soc is None else (float(initial_soc) * cap if float(initial_soc) <= 1.0 else float(initial_soc))
            initial_kwh = min(max(initial_kwh, 0.0), cap)
            for slot_idx in slot_indices:
                charge_on_var[(vehicle_id, slot_idx)] = stage2.addVar(vtype=GRB.BINARY, name=f"charge_on_{vehicle_id}_{slot_idx}")
                c_var[(vehicle_id, slot_idx)] = stage2.addVar(lb=0.0, ub=charge_max_kw, vtype=GRB.CONTINUOUS, name=f"c_{vehicle_id}_{slot_idx}")
                s_var[(vehicle_id, slot_idx)] = stage2.addVar(lb=0.0, ub=cap, vtype=GRB.CONTINUOUS, name=f"soc_{vehicle_id}_{slot_idx}")
                stage2.addConstr(
                    s_var[(vehicle_id, slot_idx)] >= soc_min,
                    name=f"soc_lower__{vehicle_id}__slot_{slot_idx}",
                )
                if slot_idx in active_slot_by_vehicle.get(vehicle_id, set()):
                    stage2.addConstr(
                        charge_on_var[(vehicle_id, slot_idx)] == 0,
                        name=f"charge_availability__{vehicle_id}__slot_{slot_idx}__trip_active",
                    )
                if slot_idx in deadhead_active_slot_by_vehicle.get(vehicle_id, set()):
                    stage2.addConstr(
                        charge_on_var[(vehicle_id, slot_idx)] == 0,
                        name=f"charge_availability__{vehicle_id}__slot_{slot_idx}__deadhead_active",
                    )
                if slot_idx not in allowed_charge_slots_by_vehicle.get(vehicle_id, set()):
                    stage2.addConstr(
                        charge_on_var[(vehicle_id, slot_idx)] == 0,
                        name=f"charge_availability__{vehicle_id}__slot_{slot_idx}__not_at_home_depot",
                    )
                stage2.addConstr(
                    c_var[(vehicle_id, slot_idx)] <= charge_max_kw * charge_on_var[(vehicle_id, slot_idx)],
                    name=f"charge_power_vehicle__{vehicle_id}__slot_{slot_idx}",
                )
            stage2.addConstr(
                s_var[(vehicle_id, slot_indices[0])] == initial_kwh,
                name=f"soc_initial__{vehicle_id}",
            )
            final_floor = max(soc_min, final_soc_floor_kwh(problem, vehicle, cap_kwh=cap))
            last_slot_idx = slot_indices[-1]
            terminal_soc_expr = _vehicle_soc_transition_kwh(
                s_var[(vehicle_id, last_slot_idx)],
                charge_power_kw=c_var[(vehicle_id, last_slot_idx)],
                timestep_h=timestep_h,
                charge_efficiency=0.95,
                drive_energy_kwh=(
                    max(
                        float(
                            trip_load_by_vehicle_slot.get(
                                (vehicle_id, last_slot_idx), 0.0
                            )
                            or 0.0
                        ),
                        0.0,
                    )
                    + max(
                        float(
                            terminal_out_of_horizon_load_by_vehicle.get(
                                vehicle_id, 0.0
                            )
                            or 0.0
                        ),
                        0.0,
                    )
                ),
            )
            stage2.addConstr(
                terminal_soc_expr >= final_floor,
                name=f"terminal_soc__{vehicle_id}__minimum",
            )
            stage2.addConstr(
                terminal_soc_expr <= cap,
                name=f"soc_upper__{vehicle_id}__terminal",
            )
            target_kwh = effective_final_soc_target_kwh(problem, vehicle, cap_kwh=cap)
            if target_kwh is not None:
                stage2.addConstr(
                    terminal_soc_expr >= target_kwh,
                    name=f"terminal_soc__{vehicle_id}__target",
                )
                terminal_policy = normalize_bev_terminal_soc_policy(
                    problem.metadata.get("bev_terminal_soc_policy"),
                    has_explicit_target=(
                        problem.metadata.get("final_soc_target_percent") is not None
                    ),
                )
                if terminal_policy is BevTerminalSocPolicy.RETURN_TO_INITIAL:
                    tolerance_kwh = self._safe_nonnegative_float(
                        problem.metadata.get(
                            "bev_terminal_soc_equality_tolerance_kwh"
                        ),
                        default=1.0e-6,
                    )
                    stage2.addConstr(
                        terminal_soc_expr <= target_kwh + tolerance_kwh,
                        name=f"terminal_soc__{vehicle_id}__return_to_initial_upper",
                    )
            for pos in range(len(slot_indices) - 1):
                slot_idx = slot_indices[pos]
                next_slot = slot_indices[pos + 1]
                load_kwh = max(float(trip_load_by_vehicle_slot.get((vehicle_id, slot_idx), 0.0) or 0.0), 0.0)
                stage2.addConstr(
                    s_var[(vehicle_id, next_slot)]
                    == _vehicle_soc_transition_kwh(
                        s_var[(vehicle_id, slot_idx)],
                        charge_power_kw=c_var[(vehicle_id, slot_idx)],
                        timestep_h=timestep_h,
                        charge_efficiency=0.95,
                        drive_energy_kwh=load_kwh,
                    ),
                    name=f"soc_transition__{vehicle_id}__slot_{slot_idx}",
                )
            for trip_id in assigned_paths.get(vehicle_id, ()):
                trip = trip_by_id.get(str(trip_id))
                if trip is None:
                    continue
                departure_slot = self._slot_index(problem, trip.departure_min)
                if (vehicle_id, departure_slot) not in s_var:
                    continue
                required = self._required_departure_soc_kwh(
                    problem,
                    vehicle,
                    trip,
                    cap_kwh=cap,
                    final_soc_floor_kwh=final_floor,
                )
                # Deadhead energy is posted to the departure slot because the
                # 15-minute state is defined at slot start.  Therefore the
                # departure readiness constraint must also cover that energy;
                # otherwise a bus could leave the depot/previous terminus
                # below the true trip-energy-plus-reserve requirement.
                required += max(
                    float(
                        deadhead_energy_before_trip.get(
                            (vehicle_id, trip.trip_id), 0.0
                        )
                        or 0.0
                    ),
                    0.0,
                )
                stage2.addConstr(
                    s_var[(vehicle_id, departure_slot)] >= required,
                    name=f"departure_soc__{vehicle_id}__{trip.trip_id}",
                )

        if assigned_bev_ids and slot_indices:
            (
                physical_charger_assignment_var,
                physical_charger_power_var,
                physical_charger_metadata,
            ) = self._add_physical_charger_assignment(
                model=stage2,
                gp=gp,
                grb=GRB,
                problem=problem,
                vehicle_by_id=vehicle_by_id,
                vehicle_ids=tuple(sorted(assigned_bev_ids)),
                slot_indices=slot_indices,
                charge_power_var=c_var,
                charge_on_var=charge_on_var,
                name_prefix="stage2_physical_charger",
            )

        depot_by_id = {depot.depot_id: depot for depot in problem.depots}
        depot_energy_assets: Dict[str, DepotEnergyAsset] = dict(problem.depot_energy_assets or {})
        if not depot_energy_assets:
            default_depot = next(iter(depot_by_id.keys()), "depot_default")
            depot_energy_assets[default_depot] = DepotEnergyAsset(depot_id=default_depot, pv_enabled=False, bess_enabled=False)
        on_peak_slots, off_peak_slots = self._classify_peak_slots(problem)
        price_by_slot = {slot.slot_index: slot.grid_buy_yen_per_kwh for slot in problem.price_slots}
        for depot_id, asset in depot_energy_assets.items():
            observed_on_peak_kw = max(
                float(
                    dict(
                        getattr(
                            config,
                            "rolling_observed_on_peak_kw_by_depot",
                            {},
                        )
                        or {}
                    ).get(depot_id, 0.0)
                    or 0.0
                ),
                0.0,
            )
            observed_off_peak_kw = max(
                float(
                    dict(
                        getattr(
                            config,
                            "rolling_observed_off_peak_kw_by_depot",
                            {},
                        )
                        or {}
                    ).get(depot_id, 0.0)
                    or 0.0
                ),
                0.0,
            )
            w_on_depot_var[depot_id] = stage2.addVar(
                lb=observed_on_peak_kw,
                vtype=GRB.CONTINUOUS,
                name=f"w_on_{depot_id}",
            )
            w_off_depot_var[depot_id] = stage2.addVar(
                lb=observed_off_peak_kw,
                vtype=GRB.CONTINUOUS,
                name=f"w_off_{depot_id}",
            )
            contract_limit_kw = float(getattr(depot_by_id.get(depot_id), "import_limit_kw", 0.0) or 0.0)
            if contract_limit_kw <= 0.0:
                contract_limit_kw = 1.0e6
            for slot_idx in slot_indices:
                key = (depot_id, slot_idx)
                g2bus_var[key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"g2bus_{depot_id}_{slot_idx}")
                pv2bus_var[key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"pv2bus_{depot_id}_{slot_idx}")
                g2bess_var[key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"g2bess_{depot_id}_{slot_idx}")
                pv2bess_var[key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"pv2bess_{depot_id}_{slot_idx}")
                bess2bus_var[key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"bess2bus_{depot_id}_{slot_idx}")
                pv_curt_var[key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"pvcurt_{depot_id}_{slot_idx}")
                grid_import_var[key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"grid_{depot_id}_{slot_idx}")
                p_avg_depot_var[key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"pavg_{depot_id}_{slot_idx}")
                vehicle_grid_terms = []
                vehicle_pv_terms = []
                vehicle_bess_terms = []
                for vehicle_id in assigned_bev_ids:
                    vehicle = vehicle_by_id[vehicle_id]
                    if str(getattr(vehicle, "home_depot_id", "") or "depot_default") != str(depot_id):
                        continue
                    vehicle_key = (vehicle_id, slot_idx)
                    g2vehicle_var[vehicle_key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"g2v_{vehicle_id}_{slot_idx}")
                    pv2vehicle_var[vehicle_key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"pv2v_{vehicle_id}_{slot_idx}")
                    bess2vehicle_var[vehicle_key] = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"bess2v_{vehicle_id}_{slot_idx}")
                    stage2.addConstr(g2vehicle_var[vehicle_key] + pv2vehicle_var[vehicle_key] + bess2vehicle_var[vehicle_key] == c_var[vehicle_key] * timestep_h)
                    vehicle_grid_terms.append(g2vehicle_var[vehicle_key])
                    vehicle_pv_terms.append(pv2vehicle_var[vehicle_key])
                    vehicle_bess_terms.append(bess2vehicle_var[vehicle_key])
                stage2.addConstr(g2bus_var[key] == gp.quicksum(vehicle_grid_terms))
                stage2.addConstr(pv2bus_var[key] == gp.quicksum(vehicle_pv_terms))
                stage2.addConstr(bess2bus_var[key] == gp.quicksum(vehicle_bess_terms))
                pv_gen_kwh = _pv_generation_kwh_at_slot(asset, slot_idx)
                stage2.addConstr(pv2bus_var[key] + pv2bess_var[key] + pv_curt_var[key] == pv_gen_kwh)
                stage2.addConstr(grid_import_var[key] == g2bus_var[key] + g2bess_var[key])
                stage2.addConstr(
                    grid_import_var[key] <= contract_limit_kw * timestep_h,
                    name=f"grid_limit__{depot_id}__slot_{slot_idx}",
                )
                stage2.addConstr(p_avg_depot_var[key] == grid_import_var[key] / timestep_h)
                if slot_idx in on_peak_slots:
                    stage2.addConstr(w_on_depot_var[depot_id] >= p_avg_depot_var[key])
                if slot_idx in off_peak_slots:
                    stage2.addConstr(w_off_depot_var[depot_id] >= p_avg_depot_var[key])
                if not asset.allow_grid_to_bess:
                    stage2.addConstr(g2bess_var[key] == 0.0)
                if not getattr(asset, "allow_pv_to_bess", True):
                    stage2.addConstr(pv2bess_var[key] == 0.0)
                if not getattr(asset, "allow_bess_to_bus", True):
                    stage2.addConstr(bess2bus_var[key] == 0.0)
                if not asset.bess_enabled:
                    stage2.addConstr(pv2bess_var[key] == 0.0)
                    stage2.addConstr(g2bess_var[key] == 0.0)
                    stage2.addConstr(bess2bus_var[key] == 0.0)
            if asset.bess_enabled and slot_indices:
                soc_lb = max(float(asset.bess_soc_min_kwh or 0.0), 0.0)
                soc_ub = max(_bess_soc_max_kwh(asset), soc_lb)
                eta_ch = max(float(asset.bess_charge_efficiency or 0.95), 1.0e-6)
                eta_dis = max(float(asset.bess_discharge_efficiency or 0.95), 1.0e-6)
                power_limit_kwh = max(float(asset.bess_power_kw or 0.0), 0.0) * timestep_h
                for slot_idx in slot_indices:
                    key = (depot_id, slot_idx)
                    bess_soc_var[key] = stage2.addVar(lb=soc_lb, ub=soc_ub, vtype=GRB.CONTINUOUS, name=f"besssoc_{depot_id}_{slot_idx}")
                    bess_charge_mode_var[key] = stage2.addVar(vtype=GRB.BINARY, name=f"bessch_{depot_id}_{slot_idx}")
                    bess_discharge_mode_var[key] = stage2.addVar(vtype=GRB.BINARY, name=f"bessdis_{depot_id}_{slot_idx}")
                    stage2.addConstr(pv2bess_var[key] + g2bess_var[key] <= power_limit_kwh * bess_charge_mode_var[key])
                    stage2.addConstr(bess2bus_var[key] <= power_limit_kwh * bess_discharge_mode_var[key])
                    stage2.addConstr(bess_charge_mode_var[key] + bess_discharge_mode_var[key] <= 1)
                stage2.addConstr(bess_soc_var[(depot_id, slot_indices[0])] == float(asset.bess_initial_soc_kwh or 0.0))
                for idx in range(len(slot_indices) - 1):
                    slot_idx = slot_indices[idx]
                    next_slot = slot_indices[idx + 1]
                    cur_key = (depot_id, slot_idx)
                    nxt_key = (depot_id, next_slot)
                    stage2.addConstr(bess_soc_var[nxt_key] == bess_soc_var[cur_key] + eta_ch * (pv2bess_var[cur_key] + g2bess_var[cur_key]) - (bess2bus_var[cur_key] / eta_dis))
                last_key = (depot_id, slot_indices[-1])
                terminal_expr = bess_soc_var[last_key] + eta_ch * (pv2bess_var[last_key] + g2bess_var[last_key]) - (bess2bus_var[last_key] / eta_dis)
                terminal_floor = max(float(asset.bess_terminal_soc_min_kwh or 0.0), soc_lb)
                stage2.addConstr(terminal_expr >= terminal_floor)
                stage2.addConstr(terminal_expr <= soc_ub)
                terminal_target = _bess_terminal_soc_target_kwh(asset, terminal_soc_floor=terminal_floor)
                if terminal_target is not None:
                    tolerance = self._safe_nonnegative_float(problem.metadata.get("bess_terminal_soc_tolerance_kwh"), default=1.0e-6)
                    stage2.addConstr(terminal_expr >= terminal_target - tolerance)
                    stage2.addConstr(terminal_expr <= terminal_target + tolerance)
        if w_on_depot_var:
            w_on_var = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="w_on")
            w_off_var = stage2.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="w_off")
            for depot_id in w_on_depot_var:
                stage2.addConstr(w_on_var >= w_on_depot_var[depot_id])
                stage2.addConstr(w_off_var >= w_off_depot_var[depot_id])

        objective2 = gp.LinExpr()
        electricity_cost_enabled = component_flags.get("electricity_cost", True)
        co2_cost_enabled = component_flags.get("co2_cost", True)
        co2_price = max(problem.scenario.co2_price_per_kg, 0.0) if co2_cost_enabled else 0.0
        co2_by_slot = {slot.slot_index: slot.co2_factor for slot in problem.price_slots}
        pv_marginal_charge_cost = self._safe_nonnegative_float(
            problem.metadata.get("pv_marginal_charge_cost_yen_per_kwh"),
            default=0.0,
        )
        pv_curtail_penalty = self._safe_nonnegative_float(
            problem.metadata.get("pv_curtail_penalty_yen_per_kwh"),
            default=0.0,
        )
        for (depot_id, slot_idx), var in g2bus_var.items():
            grid_unit_cost = (
                max(float(price_by_slot.get(slot_idx, 0.0) or 0.0), 0.0)
                if electricity_cost_enabled
                else 0.0
            )
            grid_unit_cost += co2_price * max(float(co2_by_slot.get(slot_idx, 0.0) or 0.0), 0.0)
            objective2 += grid_unit_cost * var
        for (depot_id, slot_idx), var in g2bess_var.items():
            grid_unit_cost = (
                max(float(price_by_slot.get(slot_idx, 0.0) or 0.0), 0.0)
                if electricity_cost_enabled
                else 0.0
            )
            grid_unit_cost += co2_price * max(float(co2_by_slot.get(slot_idx, 0.0) or 0.0), 0.0)
            objective2 += grid_unit_cost * var
        for (depot_id, _slot_idx), var in bess2bus_var.items():
            asset = depot_energy_assets.get(depot_id)
            if electricity_cost_enabled:
                objective2 += max(float(getattr(asset, "bess_cycle_cost_yen_per_kwh", 0.0) or 0.0), 0.0) * var
        if electricity_cost_enabled:
            for var in pv2bus_var.values():
                objective2 += pv_marginal_charge_cost * var
            for var in pv2bess_var.values():
                objective2 += pv_marginal_charge_cost * var
            for var in pv_curt_var.values():
                objective2 += pv_curtail_penalty * var
        if (
            component_flags.get("demand_charge_cost", True)
            and w_on_var is not None
            and w_off_var is not None
        ):
            objective2 += problem.scenario.demand_charge_on_peak_horizon_yen_per_kw * w_on_var
            objective2 += problem.scenario.demand_charge_off_peak_horizon_yen_per_kw * w_off_var
        stage2.setObjective(objective2, GRB.MINIMIZE)
        stage2.optimize()

        if stage2.Status == GRB.INF_OR_UNBD:
            # Distinguish a genuine IIS from an inf-or-unbounded presolve
            # ambiguity before publishing a Phase 3 rejection.
            stage2.Params.DualReductions = 0
            stage2.optimize()
        stage2_status = self._status_name(GRB, stage2.Status)
        stage2_gap = self._model_gap(stage2)
        stage2_bound = self._model_bound(stage2)
        if stage2.SolCount <= 0:
            diagnostic_metadata = self._persist_stage2_failure_diagnostics(
                problem=problem,
                stage1_plan=stage1_plan,
                stage2=stage2,
                GRB=GRB,
                assigned_paths=assigned_paths,
                allowed_charge_slots_by_vehicle=allowed_charge_slots_by_vehicle,
                blocked_charge_slots_by_vehicle={
                    vehicle_id: set(active_slot_by_vehicle.get(vehicle_id, set()))
                    | set(deadhead_active_slot_by_vehicle.get(vehicle_id, set()))
                    for vehicle_id in assigned_bev_ids
                },
                trip_load_by_vehicle_slot=trip_load_by_vehicle_slot,
                vehicle_by_id=vehicle_by_id,
                slot_indices=slot_indices,
                timestep_h=timestep_h,
                stage1_status=stage1_status,
                stage1_gap=stage1_gap,
                stage1_bound=stage1_bound,
                stage1_objective=stage1_objective_value,
                stage1_runtime_seconds=stage1_runtime_sec,
            )
            metadata = {
                **dict(stage1_plan.metadata or {}),
                "stage2_solver_status": stage2_status,
                "stage1_mip_gap": stage1_gap,
                "stage1_objective_value": stage1_objective_value,
                "stage2_mip_gap": stage2_gap,
                "stage2_objective_value": None,
                "stage1_has_feasible_incumbent": True,
                "stage1_objective": stage1_objective_value,
                "stage1_best_bound": stage1_bound,
                "stage1_mip_gap_ratio": stage1_gap,
                "stage1_runtime_seconds": stage1_runtime_sec,
                "stage2_has_feasible_incumbent": False,
                "stage2_objective": None,
                "stage2_best_bound": stage2_bound,
                "stage2_mip_gap_ratio": stage2_gap,
                "stage2_runtime_seconds": float(time.perf_counter() - started),
                "stage1_time_limit_sec_effective": (
                    0
                    if stage1_status == "phase1_fixed_assignment"
                    else _resolved_stage_time_limit_sec(config, stage=1)
                ),
                "stage2_time_limit_sec_effective": _resolved_stage_time_limit_sec(
                    config, stage=2
                ),
                "rolling_horizon_policy": rolling_policy,
                "rolling_start_slot_index": (
                    slot_indices[0] if is_remaining_day_reoptimization and slot_indices else None
                ),
                "rolling_execution_minutes": getattr(
                    config, "rolling_execution_minutes", None
                ),
                "stage1_feasible": True,
                "stage2_feasible": False,
                "supports_two_stage_milp": False,
                "supports_integrated_exact_milp": False,
                "assignment_candidate_available": True,
                "solver_objective_matches_accounting_total": False,
                "objective_semantics": (
                    "two_stage_assignment_energy_proxy_then_fixed_charging_"
                    "not_global_total_cost"
                ),
                "research_kpi_eligible": False,
                "postsolve_repair_allowed": False,
                **diagnostic_metadata,
            }
            return (
                MILPSolverOutcome(
                    solver_status=stage2_status,
                    used_backend="gurobi_two_stage",
                    supports_exact_milp=_supports_full_candidate_network_exact_milp(
                        arc_pruning_summary
                    ),
                    has_feasible_incumbent=False,
                    incumbent_count=0,
                    best_bound=stage2_bound,
                    # Stage 1 may have an incumbent, but the two-stage result
                    # has no dispatch/charging incumbent when Stage 2 fails.
                    # Do not report Stage 1's gap as an achieved final gap.
                    final_gap=None,
                    runtime_sec=stage1_runtime_sec + float(time.perf_counter() - started),
                    warm_start_applied=bool(
                        metadata.get("stage1_warm_start_applied", False)
                    ),
                    warm_start_source=str(
                        metadata.get("stage1_warm_start_source") or ""
                    ),
                ),
                replace(stage1_plan, metadata=metadata),
            )

        def _var_val(var: Any) -> float:
            try:
                return float(var.X)
            except Exception:
                return 0.0

        grid_to_bus: Dict[str, Dict[int, float]] = {}
        pv_to_bus: Dict[str, Dict[int, float]] = {}
        bess_to_bus: Dict[str, Dict[int, float]] = {}
        grid_to_bess: Dict[str, Dict[int, float]] = {}
        pv_to_bess: Dict[str, Dict[int, float]] = {}
        pv_curtail: Dict[str, Dict[int, float]] = {}
        bess_soc: Dict[str, Dict[int, float]] = {}
        bess_soc_start: Dict[str, Dict[int, float]] = {}
        bess_soc_end: Dict[str, Dict[int, float]] = {}
        vehicle_soc: Dict[str, Dict[int, float]] = {}
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

        for (depot_id, slot_idx), var in g2bus_var.items():
            value = max(_var_val(var), 0.0)
            if value > 1.0e-9:
                grid_to_bus.setdefault(depot_id, {})[slot_idx] = value
        for (depot_id, slot_idx), var in pv2bus_var.items():
            value = max(_var_val(var), 0.0)
            if value > 1.0e-9:
                pv_to_bus.setdefault(depot_id, {})[slot_idx] = value
        for (depot_id, slot_idx), var in bess2bus_var.items():
            value = max(_var_val(var), 0.0)
            if value > 1.0e-9:
                bess_to_bus.setdefault(depot_id, {})[slot_idx] = value
        for (depot_id, slot_idx), var in g2bess_var.items():
            value = max(_var_val(var), 0.0)
            if value > 1.0e-9:
                grid_to_bess.setdefault(depot_id, {})[slot_idx] = value
        for (depot_id, slot_idx), var in pv2bess_var.items():
            value = max(_var_val(var), 0.0)
            if value > 1.0e-9:
                pv_to_bess.setdefault(depot_id, {})[slot_idx] = value
        for (depot_id, slot_idx), var in pv_curt_var.items():
            value = max(_var_val(var), 0.0)
            if value > 1.0e-9:
                pv_curtail.setdefault(depot_id, {})[slot_idx] = value
        for (depot_id, slot_idx), var in bess_soc_var.items():
            asset = depot_energy_assets.get(depot_id)
            eta_ch = max(float(getattr(asset, "bess_charge_efficiency", 0.95) or 0.95), 1.0e-6)
            eta_dis = max(float(getattr(asset, "bess_discharge_efficiency", 0.95) or 0.95), 1.0e-6)
            start_soc = max(_var_val(var), 0.0)
            end_soc = start_soc + eta_ch * (max(_var_val(pv2bess_var.get((depot_id, slot_idx))), 0.0) + max(_var_val(g2bess_var.get((depot_id, slot_idx))), 0.0)) - max(_var_val(bess2bus_var.get((depot_id, slot_idx))), 0.0) / eta_dis
            bess_soc_start.setdefault(depot_id, {})[slot_idx] = start_soc
            bess_soc_end.setdefault(depot_id, {})[slot_idx] = end_soc
            bess_soc.setdefault(depot_id, {})[slot_idx] = end_soc
        for (vehicle_id, slot_idx), var in s_var.items():
            vehicle_soc.setdefault(vehicle_id, {})[slot_idx] = max(_var_val(var), 0.0)
        vehicle_initial_soc_kwh_by_vehicle: Dict[str, float] = {}
        vehicle_terminal_soc_kwh_by_vehicle: Dict[str, float] = {}
        vehicle_terminal_soc_target_kwh_by_vehicle: Dict[str, float] = {}
        vehicle_terminal_soc_drawdown_kwh_by_vehicle: Dict[str, float] = {}
        vehicle_terminal_soc_target_shortfall_kwh_by_vehicle: Dict[str, float] = {}
        vehicle_terminal_soc_target_surplus_kwh_by_vehicle: Dict[str, float] = {}
        if slot_indices:
            terminal_slot = slot_indices[-1]
            for vehicle_id in sorted(assigned_bev_ids):
                vehicle = vehicle_by_id.get(vehicle_id)
                if vehicle is None:
                    continue
                capacity_kwh = max(
                    float(getattr(vehicle, "battery_capacity_kwh", 0.0) or 0.0),
                    0.0,
                )
                initial_kwh = vehicle_initial_soc_kwh(
                    problem,
                    vehicle,
                    cap_kwh=capacity_kwh,
                )
                terminal_kwh = _vehicle_soc_transition_kwh(
                    _var_val(s_var.get((vehicle_id, terminal_slot))),
                    charge_power_kw=_var_val(c_var.get((vehicle_id, terminal_slot))),
                    timestep_h=timestep_h,
                    charge_efficiency=0.95,
                    drive_energy_kwh=(
                        max(
                            float(
                                trip_load_by_vehicle_slot.get(
                                    (vehicle_id, terminal_slot), 0.0
                                )
                                or 0.0
                            ),
                            0.0,
                        )
                        + max(
                            float(
                                terminal_out_of_horizon_load_by_vehicle.get(
                                    vehicle_id, 0.0
                                )
                                or 0.0
                            ),
                            0.0,
                        )
                    ),
                )
                target_kwh = effective_final_soc_target_kwh(
                    problem,
                    vehicle,
                    cap_kwh=capacity_kwh,
                )
                vehicle_initial_soc_kwh_by_vehicle[vehicle_id] = max(
                    float(initial_kwh), 0.0
                )
                vehicle_terminal_soc_kwh_by_vehicle[vehicle_id] = max(
                    float(terminal_kwh), 0.0
                )
                if target_kwh is not None:
                    vehicle_terminal_soc_target_kwh_by_vehicle[vehicle_id] = float(
                        target_kwh
                    )
                    vehicle_terminal_soc_target_shortfall_kwh_by_vehicle[
                        vehicle_id
                    ] = max(float(target_kwh) - float(terminal_kwh), 0.0)
                    vehicle_terminal_soc_target_surplus_kwh_by_vehicle[
                        vehicle_id
                    ] = max(float(terminal_kwh) - float(target_kwh), 0.0)
                vehicle_terminal_soc_drawdown_kwh_by_vehicle[vehicle_id] = max(
                    float(initial_kwh) - float(terminal_kwh),
                    0.0,
                )
        for (vehicle_id, slot_idx), var in c_var.items():
            charge_kw = max(_var_val(var), 0.0)
            if charge_kw <= 1.0e-6:
                continue
            vehicle = vehicle_by_id.get(vehicle_id)
            depot_id = str(getattr(vehicle, "home_depot_id", "") or "depot_default")
            selected_charger_id = next(
                (
                    charger_id
                    for (candidate_vehicle_id, charger_id, candidate_slot_idx), assignment in physical_charger_assignment_var.items()
                    if candidate_vehicle_id == vehicle_id
                    and candidate_slot_idx == slot_idx
                    and _var_val(assignment) > 0.5
                ),
                None,
            )
            if selected_charger_id is None:
                raise RuntimeError(
                    "Positive Stage 2 charging power has no selected physical charger: "
                    f"vehicle={vehicle_id}, slot={slot_idx}"
                )
            vehicle_key = (vehicle_id, slot_idx)
            for source, source_var in (
                ("grid", g2vehicle_var.get(vehicle_key)),
                ("pv", pv2vehicle_var.get(vehicle_key)),
                ("bess", bess2vehicle_var.get(vehicle_key)),
            ):
                source_kwh = max(_var_val(source_var), 0.0)
                if source_kwh <= 1.0e-9:
                    continue
                lat, lon = _depot_latlon(depot_id)
                charging_slots.append(
                    ChargingSlot(
                        vehicle_id=vehicle_id,
                        slot_index=slot_idx,
                        charger_id=selected_charger_id,
                        energy_source=source,
                        charge_kw=source_kwh / timestep_h,
                        discharge_kw=0.0,
                        charging_depot_id=depot_id,
                        charging_latitude=lat,
                        charging_longitude=lon,
                    )
                )

        final_gap = max(value for value in (stage1_gap, stage2_gap) if value is not None) if any(value is not None for value in (stage1_gap, stage2_gap)) else None
        stage2_exact_optimality_certified = _has_exact_mip_optimality_certificate(
            stage2_status,
            stage2_gap,
        )
        # Phase 3 fixes the Stage 1 assignment before optimizing charging. Its
        # combined result is therefore a feasible two-stage schedule, never an
        # integrated total-cost optimality proof. Exactness is exposed only in
        # the separate Stage 1/Stage 2 certificate fields below.
        solver_status = "feasible"
        metadata = {
            **dict(stage1_plan.metadata or {}),
            "status": solver_status,
            "stage2_solver_status": stage2_status,
            "stage2_exact_optimality_certified": stage2_exact_optimality_certified,
            "stage1_mip_gap": stage1_gap,
            "stage2_mip_gap": stage2_gap,
            "stage1_objective_value": stage1_objective_value,
            "stage2_objective_value": float(getattr(stage2, "ObjVal", 0.0) or 0.0),
            "stage1_has_feasible_incumbent": True,
            "stage1_objective": stage1_objective_value,
            "stage1_best_bound": stage1_bound,
            "stage1_mip_gap_ratio": stage1_gap,
            "stage1_runtime_seconds": stage1_runtime_sec,
            "stage2_has_feasible_incumbent": True,
            "stage2_objective": float(getattr(stage2, "ObjVal", 0.0) or 0.0),
            "stage2_best_bound": stage2_bound,
            "stage2_mip_gap_ratio": stage2_gap,
            "stage2_runtime_seconds": float(time.perf_counter() - started),
            "stage1_time_limit_sec_effective": (
                0
                if stage1_status == "phase1_fixed_assignment"
                else _resolved_stage_time_limit_sec(config, stage=1)
            ),
            "stage2_time_limit_sec_effective": _resolved_stage_time_limit_sec(
                config, stage=2
            ),
            "rolling_horizon_policy": rolling_policy,
            "rolling_start_slot_index": (
                slot_indices[0] if is_remaining_day_reoptimization and slot_indices else None
            ),
            "rolling_execution_minutes": getattr(
                config, "rolling_execution_minutes", None
            ),
            "rolling_observed_on_peak_kw_by_depot": dict(
                getattr(config, "rolling_observed_on_peak_kw_by_depot", {}) or {}
            ),
            "rolling_observed_off_peak_kw_by_depot": dict(
                getattr(config, "rolling_observed_off_peak_kw_by_depot", {}) or {}
            ),
            "rolling_objective_accounting_semantics": (
                "remaining_day_control_objective_not_additive_across_hourly_runs"
                if is_remaining_day_reoptimization
                else "single_run_objective"
            ),
            "stage1_feasible": True,
            "stage2_feasible": True,
            "solver_objective_matches_accounting_total": False,
            "objective_semantics": (
                "two_stage_assignment_energy_proxy_then_fixed_charging_"
                "not_global_total_cost"
                if stage1_status != "phase1_fixed_assignment"
                else "fixed_assignment_energy_dispatch_not_global_total_cost"
            ),
            "source_provenance_exact": True,
            # Stage 2 decides exact depot/slot source totals and exact
            # vehicle/slot charging, but it has no vehicle/source decision
            # variable.  Reporting therefore allocates the depot totals to
            # vehicles proportionally within each timestep.
            "vehicle_source_provenance_exact": False,
            "vehicle_source_allocation_policy": "proportional_by_depot_timestep",
            **physical_charger_metadata,
            "stage2_return_deadhead_soc_semantics": (
                "return_energy_subtracted_in_transition_ending_at_first_post_return_slot"
            ),
            "derived_source_split": False,
            # The Stage 1 + Stage 2 objectives are lexicographic rather than
            # one accounting-total objective. Do not let nested plan metadata
            # contradict the engine-level Phase 3 cost-KPI gate.
            "research_kpi_eligible": False,
            "research_cost_kpi_eligible": False,
            "postsolve_repair_allowed": False,
            "supports_integrated_exact_milp": False,
            "supports_two_stage_milp": True,
            "charging_dispatch_evaluated": True,
            "soc_constraints_evaluated": True,
            "two_stage_note": (
                "Stage 1 optimizes vehicle scheduling; Stage 2 optimizes "
                "charging/PV/BESS dispatch with Stage 1 EV operation fixed."
            ),
            "bev_terminal_soc_policy": str(
                (problem.metadata or {}).get("bev_terminal_soc_policy")
                or "minimum_only"
            ),
            "vehicle_initial_soc_kwh_by_vehicle": vehicle_initial_soc_kwh_by_vehicle,
            "vehicle_terminal_soc_kwh_by_vehicle": vehicle_terminal_soc_kwh_by_vehicle,
            "vehicle_terminal_soc_target_kwh_by_vehicle": vehicle_terminal_soc_target_kwh_by_vehicle,
            "vehicle_terminal_soc_drawdown_kwh_by_vehicle": vehicle_terminal_soc_drawdown_kwh_by_vehicle,
            "vehicle_terminal_soc_target_shortfall_kwh_by_vehicle": vehicle_terminal_soc_target_shortfall_kwh_by_vehicle,
            "vehicle_terminal_soc_target_surplus_kwh_by_vehicle": vehicle_terminal_soc_target_surplus_kwh_by_vehicle,
            "bev_terminal_soc_total_drawdown_kwh": float(
                sum(vehicle_terminal_soc_drawdown_kwh_by_vehicle.values())
            ),
            "bev_terminal_soc_total_target_shortfall_kwh": float(
                sum(vehicle_terminal_soc_target_shortfall_kwh_by_vehicle.values())
            ),
            "bev_terminal_soc_total_target_surplus_kwh": float(
                sum(vehicle_terminal_soc_target_surplus_kwh_by_vehicle.values())
            ),
            "bev_terminal_soc_max_abs_target_deviation_kwh": float(
                max(
                    (
                        max(
                            vehicle_terminal_soc_target_shortfall_kwh_by_vehicle.get(
                                vehicle_id, 0.0
                            ),
                            vehicle_terminal_soc_target_surplus_kwh_by_vehicle.get(
                                vehicle_id, 0.0
                            ),
                        )
                        for vehicle_id in vehicle_terminal_soc_target_kwh_by_vehicle
                    ),
                    default=0.0,
                )
            ),
            "bev_terminal_soc_balance_satisfied": bool(
                vehicle_terminal_soc_target_kwh_by_vehicle
                and max(
                    (
                        max(
                            vehicle_terminal_soc_target_shortfall_kwh_by_vehicle.get(
                                vehicle_id, 0.0
                            ),
                            vehicle_terminal_soc_target_surplus_kwh_by_vehicle.get(
                                vehicle_id, 0.0
                            ),
                        )
                        for vehicle_id in vehicle_terminal_soc_target_kwh_by_vehicle
                    ),
                    default=0.0,
                )
                <= self._safe_nonnegative_float(
                    problem.metadata.get(
                        "bev_terminal_soc_equality_tolerance_kwh"
                    ),
                    default=1.0e-6,
                )
            ),
            "bess_soc_start_kwh_by_depot_slot": bess_soc_start,
            "bess_soc_end_kwh_by_depot_slot": bess_soc_end or bess_soc,
            "canonical_source_flow_context": {
                "grid_to_bus_kwh_by_depot_slot": grid_to_bus,
                "pv_to_bus_kwh_by_depot_slot": pv_to_bus,
                "bess_to_bus_kwh_by_depot_slot": bess_to_bus,
                "pv_to_bess_kwh_by_depot_slot": pv_to_bess,
                "grid_to_bess_kwh_by_depot_slot": grid_to_bess,
                "pv_curtail_kwh_by_depot_slot": pv_curtail,
                "bess_soc_kwh_by_depot_slot": bess_soc,
                "bess_soc_start_kwh_by_depot_slot": bess_soc_start,
                "bess_soc_end_kwh_by_depot_slot": bess_soc_end or bess_soc,
                "contract_over_limit_kwh_by_depot_slot": {},
                "source_provenance_exact": True,
                "derived_source_split": False,
            },
        }
        final_plan = replace(
            stage1_plan,
            charging_slots=tuple(sorted(charging_slots, key=lambda item: (item.vehicle_id, item.slot_index, str(item.charger_id or "")))),
            grid_to_bus_kwh_by_depot_slot=grid_to_bus,
            pv_to_bus_kwh_by_depot_slot=pv_to_bus,
            bess_to_bus_kwh_by_depot_slot=bess_to_bus,
            pv_to_bess_kwh_by_depot_slot=pv_to_bess,
            grid_to_bess_kwh_by_depot_slot=grid_to_bess,
            pv_curtail_kwh_by_depot_slot=pv_curtail,
            bess_soc_kwh_by_depot_slot=bess_soc,
            contract_over_limit_kwh_by_depot_slot={},
            vehicle_soc_kwh_by_vehicle_slot=vehicle_soc,
            metadata=metadata,
        )
        return (
            MILPSolverOutcome(
                solver_status=solver_status,
                used_backend="gurobi_two_stage",
                # Phase 1 has no assignment-arc search space: the complete
                # assignment is externally fixed and this model optimizes the
                # full charging/PV/BESS/SOC formulation.  Arc-network exactness
                # is relevant only when Stage 1 was actually solved here.
                supports_exact_milp=(
                    stage1_status == "phase1_fixed_assignment"
                    or _supports_full_candidate_network_exact_milp(
                        arc_pruning_summary
                    )
                ),
                has_feasible_incumbent=True,
                incumbent_count=1,
                best_bound=stage2_bound,
                final_gap=final_gap,
                nodes_explored=None,
                runtime_sec=stage1_runtime_sec + float(time.perf_counter() - started),
                warm_start_applied=bool(
                    metadata.get("stage1_warm_start_applied", False)
                ),
                warm_start_source=str(
                    metadata.get("stage1_warm_start_source") or ""
                ),
                presolve_reduction_summary={
                    "stage1_assignment_pairs": len(stage1_plan.served_trip_ids),
                    "stage2_vehicle_count": len(assigned_bev_ids),
                    "stage2_slot_count": len(slot_indices),
                },
            ),
            final_plan,
        )

    def _persist_stage2_failure_diagnostics(
        self,
        *,
        problem: CanonicalOptimizationProblem,
        stage1_plan: AssignmentPlan,
        stage2: Any,
        GRB: Any,
        assigned_paths: Mapping[str, Tuple[str, ...]],
        allowed_charge_slots_by_vehicle: Mapping[str, Set[int]],
        blocked_charge_slots_by_vehicle: Mapping[str, Set[int]],
        trip_load_by_vehicle_slot: Mapping[Tuple[str, int], float],
        vehicle_by_id: Mapping[str, Any],
        slot_indices: Sequence[int],
        timestep_h: float,
        stage1_status: str,
        stage1_gap: Optional[float],
        stage1_bound: Optional[float],
        stage1_objective: Optional[float],
        stage1_runtime_seconds: float,
    ) -> Dict[str, Any]:
        """Persist candidate-only evidence when fixed-assignment Stage 2 fails.

        These artifacts are diagnostic inputs, never a final operating plan.
        They make an IIS actionable and expose vehicle paths that fail even
        under an optimistic, no-competition charging-energy precheck.
        """
        raw_dir = str((problem.metadata or {}).get("phase3_diagnostics_dir") or "").strip()
        if not raw_dir:
            return {"stage2_diagnostics_written": False}
        output_dir = Path(raw_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        trip_by_id = problem.trip_by_id()
        dispatch_trip_by_id = problem.dispatch_context.trips_by_id()
        route_name_by_id = {str(route.route_id): str(route.route_name or "") for route in problem.routes}
        assignment_rows: List[Dict[str, Any]] = []
        duty_rows: List[Dict[str, Any]] = []
        sequence_by_vehicle: Dict[str, int] = {}
        fragment_index_by_vehicle: Dict[str, int] = {}
        first_trip_id_by_vehicle = {
            vehicle_id: trip_ids[0]
            for vehicle_id, trip_ids in assigned_paths.items()
            if trip_ids
        }
        for vehicle_id, duties in sorted(stage1_plan.duties_by_vehicle().items()):
            vehicle = vehicle_by_id.get(vehicle_id)
            if vehicle is None:
                continue
            startup_precheck = self._startup_energy_precheck(
                problem,
                vehicle,
                trip_by_id.get(first_trip_id_by_vehicle.get(vehicle_id, "")),
                dispatch_trip_by_id=dispatch_trip_by_id,
            )
            for duty in duties:
                fragment_index_by_vehicle[vehicle_id] = (
                    fragment_index_by_vehicle.get(vehicle_id, 0) + 1
                )
                previous_trip_id: Optional[str] = None
                for leg in duty.legs:
                    trip = trip_by_id.get(str(leg.trip.trip_id))
                    if trip is None:
                        continue
                    sequence_by_vehicle[vehicle_id] = (
                        sequence_by_vehicle.get(vehicle_id, 0) + 1
                    )
                    is_vehicle_first_trip = (
                        str(trip.trip_id) == first_trip_id_by_vehicle.get(vehicle_id)
                    )
                    deadhead_before = (
                        self._deadhead_energy_kwh(
                            problem, vehicle, previous_trip_id, trip.trip_id
                        )
                        if previous_trip_id is not None
                        else (
                            startup_precheck.startup_deadhead_energy_kwh
                            if is_vehicle_first_trip
                            else 0.0
                        )
                    )
                    assignment_rows.append(
                        {
                            "vehicle_id": vehicle_id,
                            "vehicle_type": str(vehicle.vehicle_type),
                            "duty_id": str(duty.duty_id),
                            "fragment_index": fragment_index_by_vehicle[vehicle_id],
                            "sequence": sequence_by_vehicle[vehicle_id],
                            "trip_id": str(trip.trip_id),
                            "route_id": str(trip.route_id),
                            "route_name": route_name_by_id.get(str(trip.route_id), ""),
                            "departure_min": int(trip.departure_min),
                            "arrival_min": int(trip.arrival_min),
                            "origin": str(trip.origin),
                            "destination": str(trip.destination),
                            "trip_energy_kwh": self._trip_energy_kwh(
                                problem, vehicle, trip.trip_id
                            ),
                            "trip_energy_balance_residual_kwh": self._trip_energy_kwh(
                                problem, vehicle, trip.trip_id
                            )
                            * (
                                sum(
                                    self._trip_slot_energy_fraction(
                                        problem,
                                        trip.departure_min,
                                        trip.arrival_min,
                                        slot_idx,
                                    )
                                    for slot_idx in slot_indices
                                )
                                - 1.0
                            ),
                            "deadhead_energy_before_kwh": deadhead_before,
                            "startup_deadhead_min": (
                                startup_precheck.startup_deadhead_min
                                if is_vehicle_first_trip
                                else 0
                            ),
                        }
                    )
                    previous_trip_id = trip.trip_id
                duty_rows.append(
                    {
                        "vehicle_id": vehicle_id,
                        "vehicle_type": str(vehicle.vehicle_type),
                        "duty_id": str(duty.duty_id),
                        "fragment_index": fragment_index_by_vehicle[vehicle_id],
                        "trip_count": len(duty.legs),
                    }
                )

        path_rows: List[Dict[str, Any]] = []
        departure_rows: List[Dict[str, Any]] = []
        for vehicle_id, trip_ids in sorted(assigned_paths.items()):
            vehicle = vehicle_by_id.get(vehicle_id)
            if vehicle is None:
                continue
            ordered = [trip_by_id[trip_id] for trip_id in trip_ids if trip_id in trip_by_id]
            if not ordered:
                continue
            startup_precheck = self._startup_energy_precheck(
                problem,
                vehicle,
                ordered[0],
                dispatch_trip_by_id=dispatch_trip_by_id,
            )
            cap = max(float(vehicle.battery_capacity_kwh or 0.0), 1.0)
            reserve = vehicle.reserve_soc
            minimum = 0.15 * cap if reserve is None else float(reserve) * cap if float(reserve) <= 1.0 else float(reserve)
            minimum = min(max(minimum, 0.0), cap)
            initial = vehicle.initial_soc
            initial_kwh = 0.8 * cap if initial is None else float(initial) * cap if float(initial) <= 1.0 else float(initial)
            initial_kwh = min(max(initial_kwh, 0.0), cap)
            charge_max_kw = self._charge_power_max_kw(problem, vehicle.vehicle_type)
            if problem.chargers:
                charge_max_kw = min(
                    charge_max_kw,
                    max(float(charger.power_kw or 0.0) for charger in problem.chargers),
                )
            trip_energy = sum(self._trip_energy_kwh(problem, vehicle, trip.trip_id) for trip in ordered)
            connection_deadhead_energy = sum(
                self._deadhead_energy_kwh(problem, vehicle, ordered[index - 1].trip_id, trip.trip_id)
                for index, trip in enumerate(ordered)
                if index > 0
            )
            deadhead_energy = (
                startup_precheck.startup_deadhead_energy_kwh
                + connection_deadhead_energy
            )
            return_energy = return_deadhead_energy_kwh(problem, vehicle, ordered[-1])
            terminal_requirement = max(
                minimum,
                final_soc_floor_kwh(problem, vehicle, cap_kwh=cap),
                float(effective_final_soc_target_kwh(problem, vehicle, cap_kwh=cap) or 0.0),
            )
            valid_slot_indices = set(slot_indices)
            chargeable_slots = sorted(
                slot_idx
                for slot_idx in allowed_charge_slots_by_vehicle.get(vehicle_id, set())
                if slot_idx in valid_slot_indices
                and slot_idx
                not in blocked_charge_slots_by_vehicle.get(vehicle_id, set())
            )
            max_charge = len(chargeable_slots) * charge_max_kw * timestep_h * 0.95
            required = trip_energy + deadhead_energy + return_energy + terminal_requirement - minimum
            shortage = max(required - ((initial_kwh - minimum) + max_charge), 0.0)
            row = {
                "vehicle_id": vehicle_id,
                "vehicle_type": str(vehicle.vehicle_type),
                "initial_soc_kwh": initial_kwh,
                "minimum_soc_kwh": minimum,
                "terminal_soc_requirement_kwh": terminal_requirement,
                "final_soc_requirement_kwh": terminal_requirement,
                "assigned_trip_count": len(ordered),
                "assigned_trip_energy_kwh": trip_energy,
                "startup_deadhead_min": startup_precheck.startup_deadhead_min,
                "startup_deadhead_energy_kwh": startup_precheck.startup_deadhead_energy_kwh,
                "connection_deadhead_energy_kwh": connection_deadhead_energy,
                "deadhead_energy_kwh": deadhead_energy,
                "return_energy_kwh": return_energy,
                "total_required_energy_kwh": trip_energy + deadhead_energy + return_energy,
                "usable_initial_energy_kwh": initial_kwh - minimum,
                "chargeable_slot_count": len(chargeable_slots),
                "blocked_charge_slot_count": len(
                    set(allowed_charge_slots_by_vehicle.get(vehicle_id, set()))
                    .intersection(valid_slot_indices)
                    .intersection(blocked_charge_slots_by_vehicle.get(vehicle_id, set()))
                ),
                "chargeable_slot_policy": (
                    "home_depot_window_excluding_trip_and_deadhead_overlap"
                ),
                "max_chargeable_energy_kwh": max_charge,
                "required_energy_kwh": required,
                "energy_shortage_kwh": shortage,
                "individually_energy_feasible": shortage <= 1.0e-9,
                "first_departure_trip_id": str(ordered[0].trip_id),
                "first_departure_min": int(ordered[0].departure_min),
                "last_arrival_min": int(ordered[-1].arrival_min),
            }
            path_rows.append(row)
            charge_energy_per_slot = charge_max_kw * timestep_h * 0.95
            maximum_soc_before_slot: Dict[int, float] = {}
            cumulative_charge_before_slot: Dict[int, float] = {}
            maximum_soc = initial_kwh
            cumulative_charge = 0.0
            for slot_idx in sorted(valid_slot_indices):
                maximum_soc_before_slot[slot_idx] = maximum_soc
                cumulative_charge_before_slot[slot_idx] = cumulative_charge
                if slot_idx in chargeable_slots:
                    charge_added = min(
                        charge_energy_per_slot,
                        max(cap - maximum_soc, 0.0),
                    )
                    maximum_soc += charge_added
                    cumulative_charge += charge_added
                maximum_soc -= max(
                    float(
                        trip_load_by_vehicle_slot.get((vehicle_id, slot_idx), 0.0)
                        or 0.0
                    ),
                    0.0,
                )

            previous_trip: Optional[ProblemTrip] = None
            for trip in ordered:
                deadhead_before_departure = (
                    startup_precheck.startup_deadhead_energy_kwh
                    if previous_trip is None
                    else self._deadhead_energy_kwh(
                        problem,
                        vehicle,
                        previous_trip.trip_id,
                        trip.trip_id,
                    )
                )
                departure_slot = self._slot_index(problem, trip.departure_min)
                pre_slots = [slot for slot in chargeable_slots if slot < departure_slot]
                maximum_precharge = cumulative_charge_before_slot.get(
                    departure_slot
                )
                maximum_soc_before_departure = maximum_soc_before_slot.get(
                    departure_slot
                )
                required_departure = self._required_departure_soc_kwh(
                    problem,
                    vehicle,
                    trip,
                    cap_kwh=cap,
                    final_soc_floor_kwh=minimum,
                ) + deadhead_before_departure
                departure_rows.append(
                    {
                        "vehicle_id": vehicle_id,
                        "trip_id": str(trip.trip_id),
                        "departure_min": int(trip.departure_min),
                        "soc_available_before_departure_kwh": (
                            maximum_soc_before_departure
                        ),
                        "required_departure_soc_kwh": required_departure,
                        "shortage_kwh": (
                            max(
                                required_departure
                                - maximum_soc_before_departure,
                                0.0,
                            )
                            if maximum_soc_before_departure is not None
                            else None
                        ),
                        "deadhead_energy_before_departure_kwh": deadhead_before_departure,
                        "startup_deadhead_energy_kwh": deadhead_before_departure
                        if previous_trip is None
                        else 0.0,
                        "latest_chargeable_slot_before_departure": pre_slots[-1] if pre_slots else None,
                        "maximum_predeparture_charge_kwh": maximum_precharge,
                    }
                )
                previous_trip = trip

        self._write_diagnostic_csv(output_dir / "stage1_candidate_assignment.csv", assignment_rows)
        self._write_diagnostic_csv(output_dir / "stage1_candidate_vehicle_paths.csv", path_rows)
        self._write_diagnostic_csv(output_dir / "stage1_candidate_duties.csv", duty_rows)
        self._write_diagnostic_csv(output_dir / "stage1_candidate_energy_precheck.csv", path_rows)
        self._write_diagnostic_csv(output_dir / "stage2_energy_shortage_by_vehicle.csv", path_rows)
        self._write_diagnostic_csv(output_dir / "stage2_departure_soc_precheck.csv", departure_rows)

        iis_constraint_names: List[str] = []
        iis_written = False
        all_constraint_names = [
            str(constraint.ConstrName) for constraint in stage2.getConstrs()
        ]
        diagnostic_prefixes = (
            "soc_initial__",
            "soc_transition__",
            "soc_lower__",
            "soc_upper__",
            "departure_soc__",
            "terminal_soc__",
            "charge_availability__",
            "charger_ports__",
            "charger_power__",
            "grid_limit__",
        )
        constraint_count_by_prefix = {
            prefix.removesuffix("__"): sum(
                name.startswith(prefix) for name in all_constraint_names
            )
            for prefix in diagnostic_prefixes
        }
        if stage2.Status == GRB.INFEASIBLE:
            stage2.computeIIS()
            stage2.write(str(output_dir / "stage2_infeasible.ilp"))
            iis_constraint_names = [
                str(constraint.ConstrName)
                for constraint in stage2.getConstrs()
                if bool(getattr(constraint, "IISConstr", False))
            ]
            self._write_diagnostic_csv(
                output_dir / "stage2_iis_constraints.csv",
                [{"constraint_name": name} for name in iis_constraint_names],
            )
            iis_written = True
        summary = {
            "stage2_status": self._status_name(GRB, stage2.Status),
            "iis_generated": iis_written,
            "iis_constraint_count": len(iis_constraint_names),
            "iis_constraint_names": iis_constraint_names,
            "constraint_count": len(all_constraint_names),
            "constraint_count_by_prefix": constraint_count_by_prefix,
            "vehicle_soc_semantics": "slot_start",
            "terminal_soc_policy": str((problem.metadata or {}).get("terminal_soc_policy") or "configured"),
        }
        (output_dir / "stage2_constraint_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "stage1_solver_telemetry.json").write_text(
            json.dumps(
                {
                    "stage1_solver_status": stage1_status,
                    "stage1_has_feasible_incumbent": True,
                    "stage1_objective": stage1_objective,
                    "stage1_best_bound": stage1_bound,
                    "stage1_mip_gap_ratio": stage1_gap,
                    "stage1_mip_gap_percent": (
                        stage1_gap * 100.0 if stage1_gap is not None else None
                    ),
                    "stage1_runtime_seconds": stage1_runtime_seconds,
                    "candidate_trip_count": len(stage1_plan.served_trip_ids),
                    "candidate_vehicle_count": len(assigned_paths),
                    "candidate_only": True,
                    "candidate_hash": hashlib.sha256(
                        json.dumps(
                            {
                                vehicle_id: list(trip_ids)
                                for vehicle_id, trip_ids in sorted(assigned_paths.items())
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "stage2_diagnostics_written": True,
            "stage2_diagnostics_dir": str(output_dir),
            "stage2_iis_generated": iis_written,
            "stage2_iis_constraint_count": len(iis_constraint_names),
        }

    @staticmethod
    def _write_diagnostic_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
        columns = sorted({str(key) for row in rows for key in row})
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns or ["empty"])
            writer.writeheader()
            writer.writerows(rows)

    def _status_name(self, GRB: Any, status: int) -> str:
        status_map = {
            GRB.OPTIMAL: "optimal",
            GRB.TIME_LIMIT: "time_limit",
            GRB.SUBOPTIMAL: "suboptimal",
            GRB.INFEASIBLE: "infeasible",
            GRB.INF_OR_UNBD: "inf_or_unbd",
            GRB.UNBOUNDED: "unbounded",
        }
        user_obj_limit = getattr(GRB, "USER_OBJ_LIMIT", None)
        if user_obj_limit is not None:
            status_map[user_obj_limit] = "objective_limit"
        return status_map.get(status, f"status_{status}")

    def _model_gap(self, model: Any) -> Optional[float]:
        if not bool(getattr(model, "SolCount", 0) > 0) or not hasattr(model, "MIPGap"):
            return None
        try:
            value = float(model.MIPGap)
            return value if math.isfinite(value) else None
        except Exception:
            return None

    def _model_bound(self, model: Any) -> Optional[float]:
        if not hasattr(model, "ObjBound"):
            return None
        try:
            value = float(model.ObjBound)
            return value if math.isfinite(value) else None
        except Exception:
            return None

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
        baseline_unserved_trip_count = int(len(baseline_plan.unserved_trip_ids))
        partial_baseline_fallback = baseline_unserved_trip_count > 0
        baseline_meta = dict(baseline_plan.metadata or {})
        arc_pruning_summary: Dict[str, Any] = {}
        if callable(getattr(problem.dispatch_context, "trips_by_id", None)):
            arc_pruning_summary = MILPModelBuilder().arc_pruning_summary(
                problem,
                problem.trip_by_id(),
            )
        baseline_meta.update(
            {
                "source": source,
                "status": fallback_status,
                "milp_status": solver_status,
                "milp_backend": self.backend_name,
                "auto_relaxed_allow_partial_service": bool(relaxed_partial_service),
                "service_coverage_mode": service_coverage_mode,
                "strict_coverage_enforced": service_coverage_mode == "strict",
                "partial_baseline_fallback": bool(partial_baseline_fallback),
                "baseline_unserved_trip_count": baseline_unserved_trip_count,
                "arc_pruning_summary": arc_pruning_summary,
            }
        )
        return (
            MILPSolverOutcome(
                solver_status=(
                    "PARTIAL_BASELINE_FALLBACK"
                    if partial_baseline_fallback
                    else "BASELINE_FALLBACK"
                ),
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

    def _apply_stage1_assignment_warm_start(
        self,
        problem: CanonicalOptimizationProblem,
        *,
        enabled: bool,
        preferred_plan: Optional[AssignmentPlan] = None,
        y: Mapping[Tuple[str, str], Any],
        x: Mapping[Tuple[str, str, str], Any],
        start_arc: Mapping[Tuple[str, str], Any],
        end_arc: Mapping[Tuple[str, str], Any],
        used_vehicle: Mapping[str, Any],
        used_vehicle_day: Mapping[Tuple[str, int], Any],
        trip_day_index_by_trip_id: Mapping[str, int],
    ) -> Tuple[bool, str, str]:
        """Submit a complete, representable path-cover baseline as MIP start."""
        baseline = preferred_plan or problem.baseline_plan
        if not enabled:
            return False, "", "disabled_by_config"
        if baseline is None:
            return False, "", "baseline_missing"

        source = str(
            (baseline.metadata or {}).get("source")
            or (
                "stage1_candidate_plan"
                if preferred_plan is not None
                else "baseline_plan"
            )
        )
        expected_trip_ids = set(problem.eligible_trip_ids())
        if set(baseline.served_trip_ids) != expected_trip_ids or baseline.unserved_trip_ids:
            return False, source, "baseline_does_not_cover_all_trips"

        duty_vehicle_map = baseline.duty_vehicle_map()
        selected_y: Set[Tuple[str, str]] = set()
        selected_x: Set[Tuple[str, str, str]] = set()
        selected_start: Set[Tuple[str, str]] = set()
        selected_end: Set[Tuple[str, str]] = set()
        selected_used_vehicle: Set[str] = set()
        selected_used_vehicle_day: Set[Tuple[str, int]] = set()
        assigned_vehicle_by_trip: Dict[str, str] = {}

        for duty in baseline.duties:
            trip_ids = tuple(str(trip_id) for trip_id in duty.trip_ids)
            if not trip_ids:
                continue
            vehicle_id = str(duty_vehicle_map.get(str(duty.duty_id)) or "")
            if not vehicle_id or vehicle_id not in used_vehicle:
                return False, source, f"baseline_vehicle_missing:{vehicle_id or duty.duty_id}"
            selected_used_vehicle.add(vehicle_id)
            for trip_id in trip_ids:
                key = (vehicle_id, trip_id)
                if key not in y:
                    return False, source, f"baseline_assignment_not_representable:{vehicle_id}:{trip_id}"
                previous_vehicle_id = assigned_vehicle_by_trip.get(trip_id)
                if previous_vehicle_id is not None:
                    return False, source, (
                        "baseline_duplicate_assignment:"
                        f"{trip_id}:{previous_vehicle_id}:{vehicle_id}"
                    )
                assigned_vehicle_by_trip[trip_id] = vehicle_id
                selected_y.add(key)
                day_idx = int(trip_day_index_by_trip_id.get(trip_id, 0))
                day_key = (vehicle_id, day_idx)
                if day_key not in used_vehicle_day:
                    return False, source, f"baseline_vehicle_day_missing:{vehicle_id}:{day_idx}"
                selected_used_vehicle_day.add(day_key)

            start_key = (vehicle_id, trip_ids[0])
            end_key = (vehicle_id, trip_ids[-1])
            if start_key not in start_arc or end_key not in end_arc:
                return False, source, f"baseline_boundary_not_representable:{duty.duty_id}"
            selected_start.add(start_key)
            selected_end.add(end_key)
            for from_trip_id, to_trip_id in zip(trip_ids, trip_ids[1:]):
                arc_key = (vehicle_id, from_trip_id, to_trip_id)
                if arc_key not in x:
                    return False, source, (
                        "baseline_connection_not_representable:"
                        f"{vehicle_id}:{from_trip_id}:{to_trip_id}"
                    )
                selected_x.add(arc_key)

        if {trip_id for _vehicle_id, trip_id in selected_y} != expected_trip_ids:
            return False, source, "baseline_selected_trip_set_mismatch"

        for key, var in y.items():
            var.Start = 1.0 if key in selected_y else 0.0
        for key, var in x.items():
            var.Start = 1.0 if key in selected_x else 0.0
        for key, var in start_arc.items():
            var.Start = 1.0 if key in selected_start else 0.0
        for key, var in end_arc.items():
            var.Start = 1.0 if key in selected_end else 0.0
        for vehicle_id, var in used_vehicle.items():
            var.Start = 1.0 if vehicle_id in selected_used_vehicle else 0.0
        for key, var in used_vehicle_day.items():
            var.Start = 1.0 if key in selected_used_vehicle_day else 0.0
        return True, source, ""

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
        # A fragment-transition diagnosis depends on the duty endpoints, the
        # vehicle's home depot and the shared dispatch context.  The same
        # combination occurs for each vehicle of one type, so caching it avoids
        # repeatedly evaluating an identical hard-feasibility condition while
        # still adding the resulting cut for every individual vehicle.
        transition_feasible_cache: Dict[Tuple[str, str, str, str, bool, bool], bool] = {}
        for vehicle in vehicles:
            vehicle_id = str(getattr(vehicle, "vehicle_id", "") or "")
            vehicle_type = str(getattr(vehicle, "vehicle_type", "") or "")
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
                    end_arrival_min = self._trip_service_arrival_min(problem, end_trip)
                    start_departure_min = self._service_minute(
                        problem, start_trip.departure_min
                    )
                    if end_arrival_min > start_departure_min:
                        continue
                    end_key = (vehicle_id, end_trip_id)
                    start_key = (vehicle_id, start_trip_id)
                    if end_key not in end_arc or start_key not in start_arc:
                        continue
                    cache_key = (
                        vehicle_type,
                        home_depot_id,
                        str(end_trip_id),
                        str(start_trip_id),
                        fixed_route_band_mode,
                        allow_same_day_depot_cycles,
                    )
                    transition_feasible = transition_feasible_cache.get(cache_key)
                    if transition_feasible is None:
                        transition_feasible = fragment_transition_diagnostic(
                            VehicleDuty(
                                duty_id=f"{vehicle_id}__end_probe",
                                vehicle_type=vehicle_type,
                                legs=(DutyLeg(trip=end_trip),),
                            ),
                            VehicleDuty(
                                duty_id=f"{vehicle_id}__start_probe",
                                vehicle_type=vehicle_type,
                                legs=(DutyLeg(trip=start_trip),),
                            ),
                            home_depot_id=home_depot_id,
                            dispatch_context=problem.dispatch_context,
                            fixed_route_band_mode=fixed_route_band_mode,
                            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
                        ).feasible
                        transition_feasible_cache[cache_key] = transition_feasible
                    if transition_feasible:
                        continue
                    model.addConstr(end_arc[end_key] + start_arc[start_key] <= 1)
                    cut_count += 1
        return cut_count

    def _add_fragment_temporal_occupancy_constraints(
        self,
        model: Any,
        *,
        grb: Any,
        trip_by_id: Mapping[str, ProblemTrip],
        vehicles: Tuple[Any, ...],
        assignment_trip_ids_by_vehicle: Mapping[str, List[str]],
        start_arc: Mapping[Tuple[str, str], Any],
        end_arc: Mapping[Tuple[str, str], Any],
        problem: CanonicalOptimizationProblem,
    ) -> int:
        """Prevent disconnected fragments for one vehicle from overlapping.

        Trip-overlap cliques only protect the occupied interval of each trip.
        Without this cumulative fragment state, a path can connect a morning
        trip directly to a late trip while a second path for the same vehicle
        operates inside that waiting interval.  Such nested paths cannot be
        driven by one physical vehicle even though no two trip intervals
        overlap directly.
        """
        constraint_count = 0
        for vehicle in vehicles:
            vehicle_id = str(getattr(vehicle, "vehicle_id", "") or "")
            trip_ids = tuple(assignment_trip_ids_by_vehicle.get(vehicle_id, ()))
            if not trip_ids:
                continue

            starts_by_minute: Dict[int, List[Any]] = {}
            ends_by_minute: Dict[int, List[Any]] = {}
            event_minutes: Set[int] = set()
            for trip_id in trip_ids:
                trip = trip_by_id.get(trip_id)
                if trip is None:
                    continue
                start_key = (vehicle_id, trip_id)
                end_key = (vehicle_id, trip_id)
                departure_min = self._service_minute(problem, trip.departure_min)
                arrival_min = self._trip_service_arrival_min(problem, trip)
                if start_key in start_arc:
                    starts_by_minute.setdefault(departure_min, []).append(
                        start_arc[start_key]
                    )
                    event_minutes.add(departure_min)
                if end_key in end_arc:
                    ends_by_minute.setdefault(arrival_min, []).append(end_arc[end_key])
                    event_minutes.add(arrival_min)

            previous_active = None
            for event_index, event_minute in enumerate(sorted(event_minutes)):
                active = model.addVar(
                    lb=0.0,
                    ub=1.0,
                    vtype=grb.CONTINUOUS,
                    name=f"fragment_active_{vehicle_id}_{event_index}",
                )
                starts = sum(starts_by_minute.get(event_minute, ()))
                ends = sum(ends_by_minute.get(event_minute, ()))
                if previous_active is None:
                    model.addConstr(active == starts - ends)
                else:
                    model.addConstr(active == previous_active + starts - ends)
                previous_active = active
                constraint_count += 1
        return constraint_count

    def _add_stage1_energy_cost_proxy(
        self,
        model: Any,
        *,
        gp: Any,
        grb: Any,
        problem: CanonicalOptimizationProblem,
        trip_by_id: Mapping[str, ProblemTrip],
        vehicles: Tuple[Any, ...],
        assignment_trip_ids_by_vehicle: Mapping[str, List[str]],
        startup_energy_precheck_by_assignment: Mapping[
            Tuple[str, str], StartupEnergyPrecheck
        ],
        y: Mapping[Tuple[str, str], Any],
        x: Mapping[Tuple[str, str, str], Any],
        start_arc: Mapping[Tuple[str, str], Any],
        end_arc: Mapping[Tuple[str, str], Any],
        used_vehicle: Mapping[str, Any],
        component_flags: Mapping[str, bool],
    ) -> Stage1EnergyCostProxy:
        """Price an optimistic aggregate BEV source-energy requirement.

        Stage 1 does not decide charging time.  For each electric vehicle this
        proxy therefore computes only the nonnegative net replenishment needed
        to finish at the hard terminal SOC requirement.  The resulting charger
        input is pooled by home depot and may use all configured PV generation,
        usable initial BESS surplus, and then grid energy at the minimum
        time-of-use plus CO2 unit cost.

        This is a lower-bound cost surrogate: it deliberately ignores source
        timing, charger contention, grid limits, demand charges, PV/BESS timing,
        and conversion losses inside the BESS.  Stage 2 remains authoritative
        for charging feasibility and realized accounting cost.
        """
        charge_efficiency = 0.95
        electric_vehicle_types = {"BEV", "PHEV", "FCEV"}
        electricity_cost_enabled = bool(
            component_flags.get("electricity_cost", True)
        )
        co2_cost_enabled = bool(component_flags.get("co2_cost", True))
        co2_price = (
            max(float(problem.scenario.co2_price_per_kg or 0.0), 0.0)
            if co2_cost_enabled
            else 0.0
        )
        grid_unit_cost_candidates = [
            (
                max(float(slot.grid_buy_yen_per_kwh or 0.0), 0.0)
                if electricity_cost_enabled
                else 0.0
            )
            + co2_price * max(float(slot.co2_factor or 0.0), 0.0)
            for slot in problem.price_slots
        ]
        grid_unit_cost = min(grid_unit_cost_candidates, default=0.0)
        pv_unit_cost = (
            self._safe_nonnegative_float(
                problem.metadata.get("pv_marginal_charge_cost_yen_per_kwh"),
                default=0.0,
            )
            if electricity_cost_enabled
            else 0.0
        )

        arc_keys_by_vehicle: Dict[str, List[Tuple[str, str]]] = {}
        for vehicle_id, from_trip_id, to_trip_id in x:
            arc_keys_by_vehicle.setdefault(str(vehicle_id), []).append(
                (str(from_trip_id), str(to_trip_id))
            )

        external_charge_input_by_vehicle: Dict[str, Any] = {}
        net_battery_requirement_by_vehicle: Dict[str, Any] = {}
        home_depot_by_vehicle: Dict[str, str] = {}
        external_charge_inputs_by_depot: Dict[str, List[Any]] = {}
        vehicle_depot_ids: Set[str] = set()
        electric_vehicle_count = 0
        for vehicle in vehicles:
            vehicle_id = str(getattr(vehicle, "vehicle_id", "") or "")
            vehicle_type = str(
                getattr(vehicle, "vehicle_type", "") or ""
            ).upper()
            if (
                not vehicle_id
                or vehicle_type not in electric_vehicle_types
                or vehicle_id not in used_vehicle
            ):
                continue
            trip_ids = tuple(assignment_trip_ids_by_vehicle.get(vehicle_id, ()))
            if not trip_ids:
                continue
            electric_vehicle_count += 1
            depot_id = str(
                getattr(vehicle, "home_depot_id", "") or "depot_default"
            )
            vehicle_depot_ids.add(depot_id)

            capacity_kwh = max(
                float(getattr(vehicle, "battery_capacity_kwh", 0.0) or 300.0),
                1.0,
            )
            initial_soc = getattr(vehicle, "initial_soc", None)
            initial_soc_kwh = (
                0.8 * capacity_kwh
                if initial_soc is None
                else (
                    float(initial_soc) * capacity_kwh
                    if float(initial_soc) <= 1.0
                    else float(initial_soc)
                )
            )
            initial_soc_kwh = min(max(initial_soc_kwh, 0.0), capacity_kwh)
            reserve_soc = getattr(vehicle, "reserve_soc", None)
            minimum_soc_kwh = (
                0.15 * capacity_kwh
                if reserve_soc is None
                else (
                    float(reserve_soc) * capacity_kwh
                    if float(reserve_soc) <= 1.0
                    else float(reserve_soc)
                )
            )
            minimum_soc_kwh = min(max(minimum_soc_kwh, 0.0), capacity_kwh)
            terminal_requirement_kwh = max(
                minimum_soc_kwh,
                final_soc_floor_kwh(problem, vehicle, cap_kwh=capacity_kwh),
                float(
                    effective_final_soc_target_kwh(
                        problem,
                        vehicle,
                        cap_kwh=capacity_kwh,
                    )
                    or 0.0
                ),
            )

            net_battery_requirement = (
                terminal_requirement_kwh - initial_soc_kwh
            ) * used_vehicle[vehicle_id]
            positive_energy_bound_kwh = terminal_requirement_kwh
            for trip_id in trip_ids:
                assignment_key = (vehicle_id, trip_id)
                trip = trip_by_id.get(trip_id)
                if trip is None or assignment_key not in y:
                    continue
                trip_energy_kwh = self._trip_energy_kwh(
                    problem, vehicle, trip_id
                )
                net_battery_requirement += trip_energy_kwh * y[assignment_key]
                positive_energy_bound_kwh += trip_energy_kwh

                startup_var = start_arc.get(assignment_key)
                startup_precheck = startup_energy_precheck_by_assignment.get(
                    assignment_key
                )
                if startup_var is not None and startup_precheck is not None:
                    startup_energy_kwh = max(
                        float(startup_precheck.startup_deadhead_energy_kwh),
                        0.0,
                    )
                    net_battery_requirement += startup_energy_kwh * startup_var
                    positive_energy_bound_kwh += startup_energy_kwh

                end_var = end_arc.get(assignment_key)
                if end_var is not None:
                    return_energy_kwh = return_deadhead_energy_kwh(
                        problem,
                        vehicle,
                        trip,
                    )
                    net_battery_requirement += return_energy_kwh * end_var
                    positive_energy_bound_kwh += return_energy_kwh

            for from_trip_id, to_trip_id in arc_keys_by_vehicle.get(
                vehicle_id, ()
            ):
                arc_var = x.get((vehicle_id, from_trip_id, to_trip_id))
                if arc_var is None:
                    continue
                deadhead_energy_kwh = self._deadhead_energy_kwh(
                    problem,
                    vehicle,
                    from_trip_id,
                    to_trip_id,
                )
                net_battery_requirement += deadhead_energy_kwh * arc_var
                positive_energy_bound_kwh += deadhead_energy_kwh

            battery_big_m_kwh = max(
                positive_energy_bound_kwh,
                capacity_kwh,
                1.0,
            )
            source_big_m_kwh = battery_big_m_kwh / charge_efficiency
            external_charge_input = model.addVar(
                lb=0.0,
                ub=source_big_m_kwh,
                vtype=grb.CONTINUOUS,
                name=f"stage1_energy_proxy_input_kwh__{vehicle_id}",
            )
            model.addConstr(
                charge_efficiency * external_charge_input
                >= net_battery_requirement,
                name=f"stage1_energy_proxy_positive_part_lb__{vehicle_id}",
            )
            external_charge_input_by_vehicle[vehicle_id] = external_charge_input
            net_battery_requirement_by_vehicle[vehicle_id] = (
                net_battery_requirement
            )
            home_depot_by_vehicle[vehicle_id] = depot_id
            external_charge_inputs_by_depot.setdefault(depot_id, []).append(
                external_charge_input
            )

        pv_to_bus_by_depot: Dict[str, Any] = {}
        grid_to_bus_by_depot: Dict[str, Any] = {}
        bess_initial_to_bus_by_depot: Dict[str, Any] = {}
        pv_available_by_depot: Dict[str, float] = {}
        bess_initial_available_by_depot: Dict[str, float] = {}
        bess_cycle_cost_by_depot: Dict[str, float] = {}
        objective_expression = gp.LinExpr()
        for depot_id in sorted(vehicle_depot_ids):
            asset = problem.depot_energy_assets.get(depot_id)
            pv_available_kwh = (
                sum(
                    max(float(value or 0.0), 0.0)
                    for value in asset.pv_generation_kwh_by_slot
                )
                if asset is not None and bool(asset.pv_enabled)
                else 0.0
            )
            bess_initial_available_kwh = 0.0
            bess_cycle_cost = 0.0
            if (
                asset is not None
                and bool(asset.bess_enabled)
                and bool(getattr(asset, "allow_bess_to_bus", True))
            ):
                terminal_floor_kwh = max(
                    float(asset.bess_soc_min_kwh or 0.0),
                    0.0,
                )
                terminal_target_kwh = _bess_terminal_soc_target_kwh(
                    asset,
                    terminal_soc_floor=terminal_floor_kwh,
                )
                terminal_requirement_kwh = (
                    terminal_target_kwh
                    if terminal_target_kwh is not None
                    else terminal_floor_kwh
                )
                discharge_efficiency = min(
                    max(float(asset.bess_discharge_efficiency or 0.95), 1.0e-6),
                    1.0,
                )
                bess_initial_available_kwh = max(
                    float(asset.bess_initial_soc_kwh or 0.0)
                    - terminal_requirement_kwh,
                    0.0,
                ) * discharge_efficiency
                if electricity_cost_enabled:
                    bess_cycle_cost = max(
                        float(asset.bess_cycle_cost_yen_per_kwh or 0.0),
                        0.0,
                    )

            pv_available_by_depot[depot_id] = pv_available_kwh
            bess_initial_available_by_depot[depot_id] = (
                bess_initial_available_kwh
            )
            bess_cycle_cost_by_depot[depot_id] = bess_cycle_cost
            total_external_input = gp.quicksum(
                external_charge_inputs_by_depot.get(depot_id, ())
            )
            pv_var = model.addVar(
                lb=0.0,
                ub=pv_available_kwh,
                vtype=grb.CONTINUOUS,
                name=f"stage1_energy_proxy_pv_kwh__{depot_id}",
            )
            grid_var = model.addVar(
                lb=0.0,
                vtype=grb.CONTINUOUS,
                name=f"stage1_energy_proxy_grid_kwh__{depot_id}",
            )
            bess_var = model.addVar(
                lb=0.0,
                ub=bess_initial_available_kwh,
                vtype=grb.CONTINUOUS,
                name=f"stage1_energy_proxy_bess_initial_kwh__{depot_id}",
            )
            model.addConstr(
                pv_var + grid_var + bess_var == total_external_input,
                name=f"stage1_energy_proxy_source_balance__{depot_id}",
            )
            objective_expression += pv_unit_cost * pv_var
            objective_expression += grid_unit_cost * grid_var
            objective_expression += bess_cycle_cost * bess_var
            pv_to_bus_by_depot[depot_id] = pv_var
            grid_to_bus_by_depot[depot_id] = grid_var
            bess_initial_to_bus_by_depot[depot_id] = bess_var

        configuration = {
            "enabled": True,
            "semantics": (
                "aggregate_home_depot_source_energy_lower_bound_"
                "without_charging_time_or_demand_charge"
            ),
            "charge_efficiency": charge_efficiency,
            "grid_unit_cost_yen_per_kwh": grid_unit_cost,
            "grid_unit_cost_semantics": (
                "minimum_time_slot_grid_buy_plus_grid_co2_cost"
            ),
            "pv_unit_cost_yen_per_kwh": pv_unit_cost,
            "bess_cycle_cost_yen_per_kwh_by_depot": bess_cycle_cost_by_depot,
            "bess_initial_available_kwh_by_depot": (
                bess_initial_available_by_depot
            ),
            "term_definitions": {
                "external_charge_input_lower_bound_kwh": (
                    "Minimum charger-input energy implied by assigned trip, "
                    "deadhead, initial EV SOC, and terminal EV SOC after dividing "
                    "by charging efficiency. It is not a time-feasible charging schedule."
                ),
                "pv_energy_credit_upper_bound_kwh": (
                    "Whole-day PV energy allowed to offset the Stage 1 lower bound "
                    "without matching generation and charging times."
                ),
                "bess_initial_dischargeable_energy_credit_kwh": (
                    "Delivered energy available from BESS SOC above its terminal "
                    "requirement: max(initial SOC - terminal requirement, 0) "
                    "times discharge efficiency."
                ),
            },
            "electric_vehicle_count": electric_vehicle_count,
            "source_aggregation": "per_home_depot",
            "includes": (
                "trip_intertrip_startup_return_energy_and_terminal_soc",
            ),
            "excludes": (
                "charging_timing_charger_contention_grid_limit_demand_charge_"
                "and_pv_bess_timing",
            ),
        }
        weather_input = {
            "pv_available_kwh_by_depot": pv_available_by_depot,
        }
        return Stage1EnergyCostProxy(
            objective_expression=objective_expression,
            external_charge_input_by_vehicle=external_charge_input_by_vehicle,
            net_battery_requirement_by_vehicle=(
                net_battery_requirement_by_vehicle
            ),
            home_depot_by_vehicle=home_depot_by_vehicle,
            pv_to_bus_by_depot=pv_to_bus_by_depot,
            grid_to_bus_by_depot=grid_to_bus_by_depot,
            bess_initial_to_bus_by_depot=bess_initial_to_bus_by_depot,
            configuration=configuration,
            weather_input=weather_input,
        )

    @staticmethod
    def _stage1_energy_cost_proxy_result(
        proxy: Stage1EnergyCostProxy,
    ) -> Dict[str, Any]:
        """Extract an auditable solution snapshot after Stage 1 optimization."""

        def _expression_value(expression: Any) -> float:
            try:
                getter = getattr(expression, "getValue", None)
                value = float(getter() if callable(getter) else expression)
            except Exception:
                return 0.0
            return value if math.isfinite(value) else 0.0

        configuration = dict(proxy.configuration)
        charge_efficiency = max(
            float(configuration.get("charge_efficiency", 0.95) or 0.95),
            1.0e-9,
        )
        external_by_vehicle = {
            vehicle_id: max(
                _expression_value(expression),
                0.0,
            )
            / charge_efficiency
            for vehicle_id, expression in (
                proxy.net_battery_requirement_by_vehicle.items()
            )
        }
        external_by_depot: Dict[str, float] = {}
        for vehicle_id, external_kwh in external_by_vehicle.items():
            depot_id = str(
                proxy.home_depot_by_vehicle.get(vehicle_id) or "depot_default"
            )
            external_by_depot[depot_id] = (
                external_by_depot.get(depot_id, 0.0) + external_kwh
            )

        grid_unit_cost = float(
            configuration.get("grid_unit_cost_yen_per_kwh", 0.0) or 0.0
        )
        pv_unit_cost = float(
            configuration.get("pv_unit_cost_yen_per_kwh", 0.0) or 0.0
        )
        bess_costs = dict(
            configuration.get("bess_cycle_cost_yen_per_kwh_by_depot") or {}
        )
        pv_available = dict(
            proxy.weather_input.get("pv_available_kwh_by_depot") or {}
        )
        bess_available = dict(
            configuration.get("bess_initial_available_kwh_by_depot") or {}
        )
        pv_by_depot: Dict[str, float] = {}
        grid_by_depot: Dict[str, float] = {}
        bess_by_depot: Dict[str, float] = {}
        for depot_id, required_kwh in sorted(external_by_depot.items()):
            remaining_kwh = max(float(required_kwh), 0.0)
            allocations = {"pv": 0.0, "grid": 0.0, "bess": 0.0}
            sources = sorted(
                (
                    (
                        pv_unit_cost,
                        0,
                        "pv",
                        max(float(pv_available.get(depot_id, 0.0) or 0.0), 0.0),
                    ),
                    (
                        float(bess_costs.get(depot_id, 0.0) or 0.0),
                        1,
                        "bess",
                        max(float(bess_available.get(depot_id, 0.0) or 0.0), 0.0),
                    ),
                    (grid_unit_cost, 2, "grid", math.inf),
                ),
                key=lambda item: (item[0], item[1]),
            )
            for _unit_cost, _priority, source, capacity_kwh in sources:
                if remaining_kwh <= 1.0e-12:
                    break
                allocated_kwh = min(remaining_kwh, capacity_kwh)
                allocations[source] += allocated_kwh
                remaining_kwh -= allocated_kwh
            pv_by_depot[depot_id] = allocations["pv"]
            grid_by_depot[depot_id] = allocations["grid"]
            bess_by_depot[depot_id] = allocations["bess"]

        objective_jpy = (
            grid_unit_cost * sum(grid_by_depot.values())
            + pv_unit_cost * sum(pv_by_depot.values())
            + sum(
                float(bess_costs.get(depot_id, 0.0) or 0.0) * value
                for depot_id, value in bess_by_depot.items()
            )
        )
        return {
            "external_charge_input_kwh": sum(external_by_vehicle.values()),
            "external_charge_input_lower_bound_kwh": sum(
                external_by_vehicle.values()
            ),
            "external_charge_input_kwh_by_vehicle": external_by_vehicle,
            "positive_charge_vehicle_count": sum(
                value > 1.0e-7 for value in external_by_vehicle.values()
            ),
            "pv_to_bus_kwh": sum(pv_by_depot.values()),
            "pv_energy_credit_kwh": sum(pv_by_depot.values()),
            "pv_to_bus_kwh_by_depot": pv_by_depot,
            "grid_to_bus_kwh": sum(grid_by_depot.values()),
            "grid_to_bus_kwh_by_depot": grid_by_depot,
            "bess_initial_to_bus_kwh": sum(bess_by_depot.values()),
            "bess_initial_dischargeable_energy_credit_kwh": sum(
                bess_by_depot.values()
            ),
            "bess_initial_to_bus_kwh_by_depot": bess_by_depot,
            "objective_jpy": objective_jpy,
            "allocation_semantics": (
                "deterministic_minimum_cost_reconstruction_from_stage1_"
                "assignment_lower_bound"
            ),
        }

    def _add_stage1_energy_envelope_constraints(
        self,
        model: Any,
        *,
        problem: CanonicalOptimizationProblem,
        trip_by_id: Mapping[str, ProblemTrip],
        vehicles: Tuple[Any, ...],
        assignment_trip_ids_by_vehicle: Mapping[str, List[str]],
        startup_energy_precheck_by_assignment: Mapping[
            Tuple[str, str], StartupEnergyPrecheck
        ],
        y: Mapping[Tuple[str, str], Any],
        x: Mapping[Tuple[str, str, str], Any],
        start_arc: Mapping[Tuple[str, str], Any],
        end_arc: Mapping[Tuple[str, str], Any],
        used_vehicle: Mapping[str, Any],
    ) -> int:
        """Eliminate Stage-1 duties impossible under any local charge schedule.

        This is intentionally an optimistic *necessary* condition, not a
        replacement for the Stage-2 SOC model.  It ignores charger-port and
        grid competition, allows overlapping candidate windows to be counted
        more than once, and therefore can only rule out a duty when it cannot
        be energy-feasible even under assumptions favorable to that duty.

        Every potential charging term corresponds to a window considered by
        Stage 2: initial predeparture availability, confirmed home-depot
        residence between connected trips, explicit home-depot trip windows,
        and the return-to-depot window at a duty end.  This keeps the two
        stages aligned without inventing a postsolve repair path.  Startup
        deadhead is deliberately not deducted here: Stage 2 posts it only for
        the chronologically first fragment, while a Stage-1 start arc alone
        cannot identify that fragment when legacy callers allow multiple
        fragments.  Omitting it keeps this constraint a safe relaxation;
        Stage 2 remains the exact SOC feasibility check.
        """
        slot_indices = tuple(sorted({slot.slot_index for slot in problem.price_slots}))
        valid_slots = set(slot_indices)
        if not valid_slots:
            return 0

        timestep_h = max(int(problem.scenario.timestep_min), 1) / 60.0
        charge_efficiency = 0.95
        pre_window_min = self._safe_nonnegative_float(
            problem.metadata.get("home_depot_charge_pre_window_min"),
            default=float(max(problem.scenario.timestep_min, 1)) * 2.0,
        )
        post_window_min = self._safe_nonnegative_float(
            problem.metadata.get("home_depot_charge_post_window_min"),
            default=float(max(problem.scenario.timestep_min, 1)) * 2.0,
        )
        operation_start_min = self._operation_start_min(problem)
        operation_end_min = self._operation_end_min(problem)
        planning_days = max(
            int(
                problem.metadata.get("planning_days")
                or problem.scenario.planning_days
                or 1
            ),
            1,
        )

        arc_keys_by_vehicle: Dict[str, List[Tuple[str, str]]] = {}
        for vehicle_id, from_trip_id, to_trip_id in x:
            arc_keys_by_vehicle.setdefault(str(vehicle_id), []).append(
                (str(from_trip_id), str(to_trip_id))
            )

        home_window_slot_count_cache: Dict[Tuple[str, str], int] = {}
        residence_slot_count_cache: Dict[Tuple[str, str, str], int] = {}
        return_slot_count_cache: Dict[Tuple[str, str], int] = {}

        def _valid_slot_count(slots: Sequence[int]) -> int:
            return sum(int(slot_idx) in valid_slots for slot_idx in slots)

        constraint_count = 0
        electric_vehicle_types = {"BEV", "PHEV", "FCEV"}
        for vehicle in vehicles:
            vehicle_id = str(getattr(vehicle, "vehicle_id", "") or "")
            if not vehicle_id or str(getattr(vehicle, "vehicle_type", "") or "").upper() not in electric_vehicle_types:
                continue
            trip_ids = tuple(assignment_trip_ids_by_vehicle.get(vehicle_id, ()))
            if not trip_ids or vehicle_id not in used_vehicle:
                continue

            capacity_kwh = max(float(vehicle.battery_capacity_kwh or 300.0), 1.0)
            reserve_soc = vehicle.reserve_soc
            minimum_soc_kwh = (
                0.15 * capacity_kwh
                if reserve_soc is None
                else (
                    float(reserve_soc) * capacity_kwh
                    if float(reserve_soc) <= 1.0
                    else float(reserve_soc)
                )
            )
            minimum_soc_kwh = min(max(minimum_soc_kwh, 0.0), capacity_kwh)
            initial_soc = vehicle.initial_soc
            initial_soc_kwh = (
                0.8 * capacity_kwh
                if initial_soc is None
                else (
                    float(initial_soc) * capacity_kwh
                    if float(initial_soc) <= 1.0
                    else float(initial_soc)
                )
            )
            initial_soc_kwh = min(max(initial_soc_kwh, 0.0), capacity_kwh)
            terminal_requirement_kwh = max(
                minimum_soc_kwh,
                final_soc_floor_kwh(problem, vehicle, cap_kwh=capacity_kwh),
                float(
                    effective_final_soc_target_kwh(
                        problem,
                        vehicle,
                        cap_kwh=capacity_kwh,
                    )
                    or 0.0
                ),
            )
            charge_energy_per_slot_kwh = (
                self._charge_power_max_kw(problem, vehicle.vehicle_type)
                * timestep_h
                * charge_efficiency
            )
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "")

            consumed_energy = terminal_requirement_kwh * used_vehicle[vehicle_id]
            available_energy = initial_soc_kwh * used_vehicle[vehicle_id]

            for trip_id in trip_ids:
                trip = trip_by_id.get(trip_id)
                assignment_key = (vehicle_id, trip_id)
                if trip is None or assignment_key not in y:
                    continue
                consumed_energy += self._trip_energy_kwh(problem, vehicle, trip_id) * y[
                    assignment_key
                ]

                home_window_key = (home_depot_id, trip_id)
                home_window_slot_count = home_window_slot_count_cache.get(
                    home_window_key
                )
                if home_window_slot_count is None:
                    home_window_slot_count = _valid_slot_count(
                        self._collect_home_depot_window_slots(
                            problem,
                            trip,
                            home_depot_id=home_depot_id,
                            pre_window_min=pre_window_min,
                            post_window_min=post_window_min,
                        )
                    )
                    home_window_slot_count_cache[home_window_key] = (
                        home_window_slot_count
                    )
                available_energy += (
                    charge_energy_per_slot_kwh
                    * home_window_slot_count
                    * y[assignment_key]
                )

                start_key = (vehicle_id, trip_id)
                start_var = start_arc.get(start_key)
                if start_var is not None:
                    startup_precheck = startup_energy_precheck_by_assignment.get(
                        start_key
                    )
                    if startup_precheck is not None:
                        available_energy += (
                            startup_precheck.maximum_precharge_energy_kwh * start_var
                        )

                end_var = end_arc.get(start_key)
                if end_var is None:
                    continue
                return_exists, return_deadhead_min = return_deadhead_min_to_home(
                    problem,
                    vehicle,
                    trip,
                )
                if not return_exists:
                    continue
                consumed_energy += return_deadhead_energy_kwh(
                    problem,
                    vehicle,
                    trip,
                ) * end_var

                return_slot_key = (home_depot_id, trip_id)
                return_slot_count = return_slot_count_cache.get(return_slot_key)
                if return_slot_count is None:
                    post_return_slots = set(
                        self._collect_post_return_target_slots(
                            problem,
                            trip=trip,
                            day_idx=self._trip_day_index(
                                problem,
                                trip.departure_min,
                            ),
                            return_deadhead_min=int(return_deadhead_min),
                        )
                    )
                    day_idx = self._trip_day_index(problem, trip.departure_min)
                    if day_idx < planning_days - 1:
                        home_arrival_min = (
                            self._trip_service_arrival_min(problem, trip)
                            + int(return_deadhead_min)
                        )
                        post_return_slots.update(
                            self._collect_overnight_home_depot_slots(
                                problem,
                                day_idx=day_idx,
                                operation_start_min=operation_start_min,
                                operation_end_min=operation_end_min,
                                earliest_home_arrival_min=home_arrival_min,
                            )
                        )
                    return_slot_count = _valid_slot_count(
                        tuple(post_return_slots)
                    )
                    return_slot_count_cache[return_slot_key] = return_slot_count
                available_energy += (
                    charge_energy_per_slot_kwh * return_slot_count * end_var
                )

            for from_trip_id, to_trip_id in arc_keys_by_vehicle.get(vehicle_id, ()):
                arc_key = (vehicle_id, from_trip_id, to_trip_id)
                arc_var = x.get(arc_key)
                previous_trip = trip_by_id.get(from_trip_id)
                next_trip = trip_by_id.get(to_trip_id)
                if arc_var is None or previous_trip is None or next_trip is None:
                    continue
                consumed_energy += self._deadhead_energy_kwh(
                    problem,
                    vehicle,
                    from_trip_id,
                    to_trip_id,
                ) * arc_var

                residence_key = (home_depot_id, from_trip_id, to_trip_id)
                residence_slot_count = residence_slot_count_cache.get(residence_key)
                if residence_slot_count is None:
                    deadhead_min = self._connection_deadhead_min(
                        problem,
                        previous_trip,
                        next_trip,
                    )
                    residence_interval = self._home_depot_residence_interval(
                        problem,
                        vehicle,
                        previous_trip,
                        next_trip,
                        deadhead_min=deadhead_min,
                    )
                    residence_slot_count = (
                        _valid_slot_count(
                            self._slot_indices_for_interval(
                                problem,
                                residence_interval[0],
                                residence_interval[1],
                            )
                        )
                        if residence_interval is not None
                        else 0
                    )
                    residence_slot_count_cache[residence_key] = (
                        residence_slot_count
                    )
                available_energy += (
                    charge_energy_per_slot_kwh * residence_slot_count * arc_var
                )

            model.addConstr(
                consumed_energy <= available_energy,
                name=f"stage1_energy_envelope__{vehicle_id}",
            )
            constraint_count += 1
        return constraint_count

    def _add_stage1_time_indexed_soc_relaxation(
        self,
        model: Any,
        *,
        grb: Any,
        problem: CanonicalOptimizationProblem,
        trip_by_id: Mapping[str, ProblemTrip],
        vehicles: Tuple[Any, ...],
        assignment_trip_ids_by_vehicle: Mapping[str, List[str]],
        startup_energy_precheck_by_assignment: Mapping[
            Tuple[str, str], StartupEnergyPrecheck
        ],
        y: Mapping[Tuple[str, str], Any],
        x: Mapping[Tuple[str, str, str], Any],
        start_arc: Mapping[Tuple[str, str], Any],
        end_arc: Mapping[Tuple[str, str], Any],
        used_vehicle: Mapping[str, Any],
    ) -> int:
        """Add cumulative, location-aware SOC necessary conditions.

        For every electric vehicle and slot boundary, cumulative trip and
        deadhead energy may not exceed usable initial energy plus the maximum
        charge deliverable in path-supported home-depot windows.  Charging
        windows come only from a selected start arc, a selected connection
        with verified home-depot residence, or a selected end/return arc.
        Each vehicle is capped at one charge opportunity per slot.  Shared
        charger, grid, PV, and BESS limits remain relaxed, so this is still a
        necessary Stage-2 condition rather than a charging dispatch.
        """
        slot_indices = tuple(
            sorted({slot.slot_index for slot in problem.price_slots})
        )
        if not slot_indices:
            return 0

        valid_slots = set(slot_indices)
        timestep_h = max(int(problem.scenario.timestep_min), 1) / 60.0
        charge_efficiency = 0.95
        electric_vehicle_types = {"BEV", "PHEV", "FCEV"}
        operation_start_min = self._operation_start_min(problem)
        operation_end_min = self._operation_end_min(problem)
        planning_days = max(
            int(
                problem.metadata.get("planning_days")
                or problem.scenario.planning_days
                or 1
            ),
            1,
        )
        arc_keys_by_vehicle: Dict[str, List[Tuple[str, str]]] = {}
        for vehicle_id, from_trip_id, to_trip_id in x:
            arc_keys_by_vehicle.setdefault(str(vehicle_id), []).append(
                (str(from_trip_id), str(to_trip_id))
            )

        constraint_count = 0
        for vehicle in vehicles:
            vehicle_id = str(getattr(vehicle, "vehicle_id", "") or "")
            vehicle_type = str(
                getattr(vehicle, "vehicle_type", "") or ""
            ).upper()
            trip_ids = tuple(assignment_trip_ids_by_vehicle.get(vehicle_id, ()))
            if (
                not vehicle_id
                or vehicle_type not in electric_vehicle_types
                or not trip_ids
                or vehicle_id not in used_vehicle
            ):
                continue

            capacity_kwh = max(
                float(vehicle.battery_capacity_kwh or 300.0), 1.0
            )
            reserve_soc = vehicle.reserve_soc
            minimum_soc_kwh = (
                0.15 * capacity_kwh
                if reserve_soc is None
                else (
                    float(reserve_soc) * capacity_kwh
                    if float(reserve_soc) <= 1.0
                    else float(reserve_soc)
                )
            )
            minimum_soc_kwh = min(max(minimum_soc_kwh, 0.0), capacity_kwh)
            initial_soc = vehicle.initial_soc
            initial_soc_kwh = (
                0.8 * capacity_kwh
                if initial_soc is None
                else (
                    float(initial_soc) * capacity_kwh
                    if float(initial_soc) <= 1.0
                    else float(initial_soc)
                )
            )
            initial_soc_kwh = min(max(initial_soc_kwh, 0.0), capacity_kwh)
            usable_initial_energy = (
                initial_soc_kwh - minimum_soc_kwh
            ) * used_vehicle[vehicle_id]

            charge_max_kw = self._charge_power_max_kw(
                problem, str(vehicle.vehicle_type)
            )
            if problem.chargers:
                max_charger_kw = max(
                    float(charger.power_kw or 0.0)
                    for charger in problem.chargers
                )
                if max_charger_kw > 0.0:
                    charge_max_kw = min(charge_max_kw, max_charger_kw)
            delivered_charge_cap_kwh = max(
                charge_max_kw * timestep_h * charge_efficiency,
                0.0,
            )
            load_terms_by_slot: Dict[int, List[Any]] = {
                slot_idx: [] for slot_idx in slot_indices
            }
            charge_terms_by_slot: Dict[int, List[Any]] = {
                slot_idx: [] for slot_idx in slot_indices
            }
            terminal_load_terms: List[Any] = []

            for trip_id in trip_ids:
                trip = trip_by_id.get(trip_id)
                assignment_key = (vehicle_id, trip_id)
                assignment_var = y.get(assignment_key)
                if trip is None or assignment_var is None:
                    continue
                trip_energy_kwh = self._trip_energy_kwh(
                    problem, vehicle, trip_id
                )
                for slot_idx in slot_indices:
                    energy_fraction = self._trip_slot_energy_fraction(
                        problem,
                        trip.departure_min,
                        trip.arrival_min,
                        slot_idx,
                    )
                    if energy_fraction > 0.0:
                        load_terms_by_slot[slot_idx].append(
                            trip_energy_kwh * energy_fraction * assignment_var
                        )
                start_var = start_arc.get(assignment_key)
                startup_precheck = startup_energy_precheck_by_assignment.get(
                    assignment_key
                )
                if start_var is not None and startup_precheck is not None:
                    complete_count = min(
                        int(startup_precheck.complete_precharge_slot_count),
                        len(slot_indices),
                    )
                    for slot_idx in slot_indices[:complete_count]:
                        charge_terms_by_slot[slot_idx].append(start_var)
                    departure_slot = self._slot_index(
                        problem, trip.departure_min
                    )
                    startup_energy_kwh = max(
                        float(startup_precheck.startup_deadhead_energy_kwh),
                        0.0,
                    )
                    if departure_slot in valid_slots:
                        load_terms_by_slot[departure_slot].append(
                            startup_energy_kwh * start_var
                        )
                    elif startup_energy_kwh > 0.0:
                        terminal_load_terms.append(startup_energy_kwh * start_var)
                end_var = end_arc.get(assignment_key)
                if end_var is None:
                    continue
                return_exists, return_deadhead_min = return_deadhead_min_to_home(
                    problem,
                    vehicle,
                    trip,
                )
                if not return_exists:
                    continue
                day_idx = self._trip_day_index(problem, trip.departure_min)
                return_slot = slot_index_ceil(
                    problem,
                    self._trip_service_arrival_min(problem, trip)
                    + int(return_deadhead_min),
                )
                return_transition_slot = _transition_slot_ending_at_event(
                    slot_indices,
                    return_slot,
                )
                return_energy_kwh = return_deadhead_energy_kwh(
                    problem, vehicle, trip
                )
                if return_transition_slot is None:
                    terminal_load_terms.append(return_energy_kwh * end_var)
                else:
                    load_terms_by_slot[return_transition_slot].append(
                        return_energy_kwh * end_var
                    )
                for slot_idx in self._collect_post_return_target_slots(
                    problem,
                    trip=trip,
                    day_idx=day_idx,
                    return_deadhead_min=int(return_deadhead_min),
                ):
                    if slot_idx in valid_slots:
                        charge_terms_by_slot[slot_idx].append(end_var)
                if day_idx < planning_days - 1:
                    home_arrival_min = (
                        self._trip_service_arrival_min(problem, trip)
                        + int(return_deadhead_min)
                    )
                    for slot_idx in self._collect_overnight_home_depot_slots(
                        problem,
                        day_idx=day_idx,
                        operation_start_min=operation_start_min,
                        operation_end_min=operation_end_min,
                        earliest_home_arrival_min=home_arrival_min,
                    ):
                        if slot_idx in valid_slots:
                            charge_terms_by_slot[slot_idx].append(end_var)

            for from_trip_id, to_trip_id in arc_keys_by_vehicle.get(
                vehicle_id, ()
            ):
                arc_var = x.get((vehicle_id, from_trip_id, to_trip_id))
                previous_trip = trip_by_id.get(from_trip_id)
                next_trip = trip_by_id.get(to_trip_id)
                if arc_var is None or previous_trip is None or next_trip is None:
                    continue
                deadhead_min = self._connection_deadhead_min(
                    problem, previous_trip, next_trip
                )
                departure_slot = self._slot_index(
                    problem, next_trip.departure_min
                )
                deadhead_energy_kwh = self._deadhead_energy_kwh(
                    problem,
                    vehicle,
                    from_trip_id,
                    to_trip_id,
                )
                if departure_slot in valid_slots:
                    load_terms_by_slot[departure_slot].append(
                        deadhead_energy_kwh * arc_var
                    )
                elif deadhead_energy_kwh > 0.0:
                    terminal_load_terms.append(deadhead_energy_kwh * arc_var)
                residence_interval = self._home_depot_residence_interval(
                    problem,
                    vehicle,
                    previous_trip,
                    next_trip,
                    deadhead_min=deadhead_min,
                )
                if residence_interval is None:
                    continue
                residence_slots = set(
                    self._slot_indices_for_interval(
                        problem,
                        residence_interval[0],
                        residence_interval[1],
                    )
                )
                if deadhead_min > 0:
                    deadhead_interval = self._connection_deadhead_interval(
                        problem,
                        vehicle,
                        previous_trip,
                        next_trip,
                        deadhead_min=deadhead_min,
                    )
                    residence_slots.difference_update(
                        self._slot_indices_for_interval(
                            problem,
                            deadhead_interval[0],
                            deadhead_interval[1],
                        )
                    )
                for slot_idx in residence_slots.intersection(valid_slots):
                    charge_terms_by_slot[slot_idx].append(arc_var)

            charge_availability_by_slot: Dict[int, Any] = {}
            for slot_idx in slot_indices:
                opportunity_terms = charge_terms_by_slot[slot_idx]
                if not opportunity_terms:
                    continue
                charge_availability = model.addVar(
                    lb=0.0,
                    ub=1.0,
                    vtype=grb.CONTINUOUS,
                    name=(
                        "stage1_charge_available__"
                        f"{vehicle_id}__slot_{slot_idx}"
                    ),
                )
                model.addConstr(
                    charge_availability <= sum(opportunity_terms),
                    name=(
                        "stage1_charge_window_support__"
                        f"{vehicle_id}__slot_{slot_idx}"
                    ),
                )
                constraint_count += 1
                charge_availability_by_slot[slot_idx] = charge_availability

            cumulative_load = 0.0
            cumulative_charge_opportunities = 0.0
            for slot_idx in slot_indices:
                model.addConstr(
                    cumulative_load
                    <= usable_initial_energy
                    + delivered_charge_cap_kwh
                    * cumulative_charge_opportunities,
                    name=(
                        "stage1_soc_relax_cumulative__"
                        f"{vehicle_id}__slot_{slot_idx}"
                    ),
                )
                constraint_count += 1
                cumulative_load += sum(load_terms_by_slot[slot_idx])
                cumulative_charge_opportunities += (
                    charge_availability_by_slot.get(slot_idx, 0.0)
                )
            cumulative_load += sum(terminal_load_terms)
            model.addConstr(
                cumulative_load
                <= usable_initial_energy
                + delivered_charge_cap_kwh * cumulative_charge_opportunities,
                name=f"stage1_soc_relax_cumulative_terminal__{vehicle_id}",
            )
            constraint_count += 1

        return constraint_count

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
        dep = self._service_minute(problem, int(trip.departure_min))
        arr = self._trip_service_arrival_min(problem, trip)

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
        earliest_home_arrival_min: Optional[int] = None,
    ) -> Tuple[int, ...]:
        horizon_start_min = self._horizon_start_min(problem)
        day_start = horizon_start_min + day_idx * 24 * 60
        end_offset = operation_end_min - operation_start_min
        if end_offset <= 0:
            end_offset += 24 * 60
        overnight_start = day_start + end_offset
        overnight_end = day_start + 24 * 60
        if earliest_home_arrival_min is not None:
            first_home_slot = slot_index_ceil(problem, int(earliest_home_arrival_min))
            first_home_slot_start = self._horizon_start_min(problem) + first_home_slot * int(
                problem.scenario.timestep_min
            )
            overnight_start = max(overnight_start, first_home_slot_start)
        if overnight_end <= overnight_start:
            return ()
        return self._slot_indices_for_interval(problem, overnight_start, overnight_end)

    def _collect_post_return_target_slots(
        self,
        problem: CanonicalOptimizationProblem,
        *,
        trip: ProblemTrip,
        day_idx: int,
        return_deadhead_min: int,
    ) -> Tuple[int, ...]:
        return_complete_min = self._trip_service_arrival_min(problem, trip) + max(
            int(return_deadhead_min or 0), 0
        )
        target_slot = post_return_target_slot_index(problem, day_idx)
        first_slot = slot_index_ceil(problem, return_complete_min)
        if target_slot < first_slot:
            return ()
        return tuple(range(first_slot, target_slot + 1))

    def _is_replenishment_slot_allowed(
        self,
        problem: CanonicalOptimizationProblem,
        slot_idx: int,
    ) -> bool:
        # ``allow_overnight_depot_moves`` governs vehicle repositioning, not
        # charging.  A bus already at its depot may charge overnight even when
        # overnight vehicle movements are forbidden.  Location eligibility is
        # enforced separately by the home-depot charging-window constraints.
        del problem, slot_idx
        return True

    def _is_in_overnight_window(
        self,
        minute_of_day: int,
        start_hhmm: str,
        end_hhmm: str,
    ) -> bool:
        def _parse(text: str, fallback: int) -> int:
            try:
                hh, mm = str(text).split(":", 1)
                return (int(hh) * 60 + int(mm)) % (24 * 60)
            except ValueError:
                return fallback

        start = _parse(start_hhmm, 23 * 60)
        end = _parse(end_hhmm, 5 * 60)
        value = int(minute_of_day) % (24 * 60)
        if start <= end:
            return start <= value <= end
        return value >= start or value <= end

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
                    self._service_minute(
                        problem, trip_by_id[trip_id].departure_min
                    ),
                    self._trip_service_arrival_min(
                        problem, trip_by_id[trip_id]
                    ),
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
                    self._service_minute(
                        problem, trip_by_id[trip_id].departure_min
                    ),
                    self._trip_service_arrival_min(
                        problem, trip_by_id[trip_id]
                    ),
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

    def _startup_energy_precheck(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        trip: ProblemTrip | None,
        *,
        dispatch_trip_by_id: Optional[Mapping[str, Any]] = None,
    ) -> StartupEnergyPrecheck:
        """Check an optimistic but physically necessary startup-SOC condition."""
        if vehicle is None or trip is None:
            return StartupEnergyPrecheck(
                path_feasible=False,
                energy_feasible=False,
                initial_soc_kwh=0.0,
                minimum_soc_kwh=0.0,
                startup_deadhead_min=0,
                startup_deadhead_energy_kwh=0.0,
                required_departure_soc_kwh=0.0,
                complete_precharge_slot_count=0,
                maximum_precharge_energy_kwh=0.0,
                energy_margin_kwh=float("-inf"),
            )

        home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
        if dispatch_trip_by_id is None:
            dispatch_trips_by_id = getattr(
                problem.dispatch_context, "trips_by_id", None
            )
            dispatch_trip_by_id = (
                dispatch_trips_by_id() if callable(dispatch_trips_by_id) else {}
            )
        dispatch_trip = dispatch_trip_by_id.get(trip.trip_id)
        startup_result = evaluate_startup_feasibility(
            dispatch_trip if dispatch_trip is not None else trip,
            problem.dispatch_context,
            home_depot_id,
            earliest_available_min=self._startup_earliest_available_min(
                problem, trip
            ),
        )
        path_feasible = bool(startup_result.feasible)
        startup_deadhead_min = max(int(startup_result.deadhead_time_min or 0), 0)
        is_electric = str(getattr(vehicle, "vehicle_type", "") or "").upper() in {
            "BEV",
            "PHEV",
            "FCEV",
        }
        if not is_electric:
            return StartupEnergyPrecheck(
                path_feasible=path_feasible,
                energy_feasible=path_feasible,
                initial_soc_kwh=0.0,
                minimum_soc_kwh=0.0,
                startup_deadhead_min=startup_deadhead_min,
                startup_deadhead_energy_kwh=0.0,
                required_departure_soc_kwh=0.0,
                complete_precharge_slot_count=0,
                maximum_precharge_energy_kwh=0.0,
                energy_margin_kwh=0.0 if path_feasible else float("-inf"),
            )

        capacity_kwh = max(float(vehicle.battery_capacity_kwh or 300.0), 1.0)
        reserve = vehicle.reserve_soc
        minimum_soc_kwh = (
            0.15 * capacity_kwh
            if reserve is None
            else (
                float(reserve) * capacity_kwh
                if float(reserve) <= 1.0
                else float(reserve)
            )
        )
        minimum_soc_kwh = min(max(minimum_soc_kwh, 0.0), capacity_kwh)
        initial = vehicle.initial_soc
        initial_soc_kwh = (
            0.8 * capacity_kwh
            if initial is None
            else (
                float(initial) * capacity_kwh
                if float(initial) <= 1.0
                else float(initial)
            )
        )
        initial_soc_kwh = min(max(initial_soc_kwh, 0.0), capacity_kwh)
        startup_deadhead_energy_kwh = self._deadhead_distance_km(
            problem, startup_deadhead_min
        ) * self._vehicle_energy_rate_kwh_per_km(problem, vehicle, trip)

        departure_min = self._service_minute(problem, int(trip.departure_min))
        leave_depot_min = departure_min - startup_deadhead_min
        timestep_min = max(int(problem.scenario.timestep_min), 1)
        complete_precharge_slot_count = max(
            (leave_depot_min - self._horizon_start_min(problem)) // timestep_min,
            0,
        )
        theoretical_precharge_kwh = (
            complete_precharge_slot_count
            * self._charge_power_max_kw(problem, vehicle.vehicle_type)
            * (timestep_min / 60.0)
            * 0.95
        )
        maximum_precharge_energy_kwh = min(
            max(theoretical_precharge_kwh, 0.0),
            max(capacity_kwh - initial_soc_kwh, 0.0),
        )
        final_floor_kwh = max(
            minimum_soc_kwh,
            final_soc_floor_kwh(problem, vehicle, cap_kwh=capacity_kwh),
        )
        required_departure_soc_kwh = (
            self._required_departure_soc_kwh(
                problem,
                vehicle,
                trip,
                cap_kwh=capacity_kwh,
                final_soc_floor_kwh=final_floor_kwh,
            )
            + startup_deadhead_energy_kwh
        )
        energy_margin_kwh = (
            initial_soc_kwh
            + maximum_precharge_energy_kwh
            - required_departure_soc_kwh
        )
        energy_feasible = bool(
            path_feasible
            and initial_soc_kwh >= minimum_soc_kwh - 1.0e-9
            and energy_margin_kwh >= -1.0e-9
        )
        return StartupEnergyPrecheck(
            path_feasible=path_feasible,
            energy_feasible=energy_feasible,
            initial_soc_kwh=initial_soc_kwh,
            minimum_soc_kwh=minimum_soc_kwh,
            startup_deadhead_min=startup_deadhead_min,
            startup_deadhead_energy_kwh=startup_deadhead_energy_kwh,
            required_departure_soc_kwh=required_departure_soc_kwh,
            complete_precharge_slot_count=complete_precharge_slot_count,
            maximum_precharge_energy_kwh=maximum_precharge_energy_kwh,
            energy_margin_kwh=energy_margin_kwh,
        )

    def _startup_earliest_available_min(
        self,
        problem: CanonicalOptimizationProblem,
        trip: ProblemTrip,
    ) -> int:
        """Express the service-day horizon start on a trip's wall-clock axis."""
        horizon_start = self._horizon_start_min(problem)
        if int(trip.departure_min) < horizon_start:
            return horizon_start - 24 * 60
        return horizon_start

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

    def _vehicle_charge_power_max_kw(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
    ) -> float:
        concrete_limit = getattr(vehicle, "charge_power_max_kw", None)
        if concrete_limit is not None:
            return max(float(concrete_limit), 0.0)
        return self._charge_power_max_kw(problem, str(vehicle.vehicle_type))

    def _add_physical_charger_assignment(
        self,
        *,
        model: Any,
        gp: Any,
        grb: Any,
        problem: CanonicalOptimizationProblem,
        vehicle_by_id: Mapping[str, Any],
        vehicle_ids: Sequence[str],
        slot_indices: Sequence[int],
        charge_power_var: Mapping[Tuple[str, int], Any],
        charge_on_var: Mapping[Tuple[str, int], Any],
        name_prefix: str,
    ) -> Tuple[Dict[Tuple[str, str, int], Any], Dict[Tuple[str, str, int], Any], Dict[str, Any]]:
        """Assign every active charge session to one physical charger type.

        A charger definition may represent multiple identical ports through
        ``simultaneous_ports``.  Empty vehicle compatibility is an explicit
        legacy contract meaning all positive-power chargers at its home depot.
        """

        charger_by_id: Dict[str, Any] = {}
        for charger in problem.chargers:
            charger_id = str(charger.charger_id).strip()
            if not charger_id:
                raise ValueError("Physical charger_id must not be empty")
            if charger_id in charger_by_id:
                raise ValueError(f"Duplicate physical charger_id: {charger_id}")
            charger_by_id[charger_id] = charger

        assignment_var: Dict[Tuple[str, str, int], Any] = {}
        power_var: Dict[Tuple[str, str, int], Any] = {}
        candidates_by_vehicle: Dict[str, Tuple[str, ...]] = {}
        implicit_compatibility_vehicle_ids: List[str] = []

        for vehicle_id in vehicle_ids:
            vehicle = vehicle_by_id[vehicle_id]
            home_depot_id = str(
                getattr(vehicle, "home_depot_id", "") or "depot_default"
            )
            explicit_ids = tuple(
                str(charger_id)
                for charger_id in (
                    getattr(vehicle, "compatible_charger_ids", ()) or ()
                )
            )
            if not explicit_ids:
                implicit_compatibility_vehicle_ids.append(vehicle_id)
            else:
                unknown_ids = sorted(set(explicit_ids) - set(charger_by_id))
                if unknown_ids:
                    raise ValueError(
                        f"Vehicle {vehicle_id} references unknown compatible "
                        f"charger IDs: {unknown_ids}"
                    )
                wrong_depot_ids = sorted(
                    charger_id
                    for charger_id in explicit_ids
                    if str(
                        charger_by_id[charger_id].depot_id or "depot_default"
                    )
                    != home_depot_id
                )
                if wrong_depot_ids:
                    raise ValueError(
                        f"Vehicle {vehicle_id} at depot {home_depot_id} references "
                        f"chargers at another depot: {wrong_depot_ids}"
                    )
            candidates = tuple(
                charger_id
                for charger_id, charger in sorted(charger_by_id.items())
                if str(charger.depot_id or "depot_default") == home_depot_id
                and float(charger.power_kw or 0.0) > 0.0
                and (not explicit_ids or charger_id in explicit_ids)
            )
            candidates_by_vehicle[vehicle_id] = candidates
            vehicle_limit_kw = self._vehicle_charge_power_max_kw(problem, vehicle)
            for slot_idx in slot_indices:
                if not candidates:
                    model.addConstr(
                        charge_on_var[(vehicle_id, slot_idx)] == 0,
                        name=f"{name_prefix}_unavailable__{vehicle_id}__slot_{slot_idx}",
                    )
                    model.addConstr(
                        charge_power_var[(vehicle_id, slot_idx)] == 0,
                        name=f"{name_prefix}_power_unavailable__{vehicle_id}__slot_{slot_idx}",
                    )
                    continue
                for charger_id in candidates:
                    charger = charger_by_id[charger_id]
                    key = (vehicle_id, charger_id, slot_idx)
                    assignment_var[key] = model.addVar(
                        vtype=grb.BINARY,
                        name=f"{name_prefix}_on__{vehicle_id}__{charger_id}__slot_{slot_idx}",
                    )
                    power_limit_kw = min(
                        vehicle_limit_kw,
                        max(float(charger.power_kw or 0.0), 0.0),
                    )
                    power_var[key] = model.addVar(
                        lb=0.0,
                        ub=power_limit_kw,
                        vtype=grb.CONTINUOUS,
                        name=f"{name_prefix}_kw__{vehicle_id}__{charger_id}__slot_{slot_idx}",
                    )
                    model.addConstr(
                        power_var[key] <= power_limit_kw * assignment_var[key],
                        name=f"{name_prefix}_link__{vehicle_id}__{charger_id}__slot_{slot_idx}",
                    )
                model.addConstr(
                    gp.quicksum(
                        assignment_var[(vehicle_id, charger_id, slot_idx)]
                        for charger_id in candidates
                    )
                    == charge_on_var[(vehicle_id, slot_idx)],
                    name=f"{name_prefix}_one__{vehicle_id}__slot_{slot_idx}",
                )
                model.addConstr(
                    gp.quicksum(
                        power_var[(vehicle_id, charger_id, slot_idx)]
                        for charger_id in candidates
                    )
                    == charge_power_var[(vehicle_id, slot_idx)],
                    name=f"{name_prefix}_power_sum__{vehicle_id}__slot_{slot_idx}",
                )

        for charger_id, charger in sorted(charger_by_id.items()):
            ports = max(int(charger.simultaneous_ports or 1), 1)
            charger_power_kw = max(float(charger.power_kw or 0.0), 0.0)
            for slot_idx in slot_indices:
                keys = [
                    (vehicle_id, charger_id, slot_idx)
                    for vehicle_id in vehicle_ids
                    if (vehicle_id, charger_id, slot_idx) in assignment_var
                ]
                if not keys:
                    continue
                model.addConstr(
                    gp.quicksum(assignment_var[key] for key in keys) <= ports,
                    name=f"{name_prefix}_ports__{charger_id}__slot_{slot_idx}",
                )
                model.addConstr(
                    gp.quicksum(power_var[key] for key in keys)
                    <= charger_power_kw * ports,
                    name=f"{name_prefix}_capacity__{charger_id}__slot_{slot_idx}",
                )

        metadata = {
            "physical_charger_assignment_semantics": (
                "one_physical_charger_definition_per_active_vehicle_slot; "
                "simultaneous_ports_are_identical_ports"
            ),
            "physical_charger_assignment_variable_count": len(assignment_var),
            "physical_charger_power_variable_count": len(power_var),
            "implicit_home_depot_charger_compatibility_vehicle_ids": tuple(
                sorted(implicit_compatibility_vehicle_ids)
            ),
            "vehicle_compatible_charger_ids": {
                vehicle_id: candidates_by_vehicle[vehicle_id]
                for vehicle_id in sorted(candidates_by_vehicle)
            },
        }
        return assignment_var, power_var, metadata

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
        dep = self._service_minute(problem, departure_min)
        arr = self._service_minute(problem, arrival_min)
        if arr < dep:
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
        
        dep = self._service_minute(problem, departure_min)
        arr = self._service_minute(problem, arrival_min)
        if arr < dep:
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

    def _service_minute(self, problem: CanonicalOptimizationProblem, minute: int) -> int:
        """Map a wall-clock minute to the service day beginning at horizon start."""
        value = int(minute)
        horizon_start_min = self._horizon_start_min(problem)
        if value < horizon_start_min:
            value += 24 * 60
        return value

    def _trip_service_arrival_min(
        self,
        problem: CanonicalOptimizationProblem,
        trip: ProblemTrip,
    ) -> int:
        departure_min = self._service_minute(problem, int(trip.departure_min))
        arrival_min = self._service_minute(problem, int(trip.arrival_min))
        if arrival_min < departure_min:
            arrival_min += 24 * 60
        return arrival_min

    def _trip_service_sort_key(
        self,
        problem: CanonicalOptimizationProblem,
        trip: ProblemTrip,
    ) -> Tuple[int, int]:
        return (
            self._trip_service_arrival_min(problem, trip),
            self._service_minute(problem, int(trip.departure_min)),
        )

    def _locations_equivalent(
        self,
        problem: CanonicalOptimizationProblem,
        left: str,
        right: str,
    ) -> bool:
        checker = getattr(problem.dispatch_context, "locations_equivalent", None)
        if callable(checker):
            return bool(checker(str(left), str(right)))
        return str(left) == str(right)

    def _connection_deadhead_min(
        self,
        problem: CanonicalOptimizationProblem,
        previous_trip: ProblemTrip,
        next_trip: ProblemTrip,
    ) -> int:
        if self._locations_equivalent(
            problem, previous_trip.destination, next_trip.origin
        ):
            return 0
        lookup = getattr(problem.dispatch_context, "get_deadhead_min", None)
        if not callable(lookup):
            return 0
        return max(
            int(lookup(previous_trip.destination, next_trip.origin) or 0),
            0,
        )

    def _turnaround_min(
        self,
        problem: CanonicalOptimizationProblem,
        location: str,
    ) -> int:
        lookup = getattr(problem.dispatch_context, "get_turnaround_min", None)
        if not callable(lookup):
            return 0
        return max(int(lookup(location) or 0), 0)

    def _home_depot_residence_interval(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        previous_trip: ProblemTrip,
        next_trip: ProblemTrip,
        *,
        deadhead_min: int,
    ) -> Optional[Tuple[int, int]]:
        """Return a confirmed at-home interval between connected trips."""
        home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "")
        previous_at_home = self._locations_equivalent(
            problem, previous_trip.destination, home_depot_id
        )
        next_at_home = self._locations_equivalent(
            problem, next_trip.origin, home_depot_id
        )
        if not previous_at_home and not next_at_home:
            return None
        if previous_at_home != next_at_home and int(deadhead_min) <= 0:
            # A zero lookup between distinct known locations is not evidence
            # that the vehicle reached the depot; do not invent residence.
            return None

        previous_arrival = self._trip_service_arrival_min(problem, previous_trip)
        next_departure = self._service_minute(
            problem, int(next_trip.departure_min)
        )
        if previous_at_home:
            residence_start = previous_arrival
        else:
            residence_start = (
                previous_arrival
                + self._turnaround_min(problem, previous_trip.destination)
                + max(int(deadhead_min), 0)
            )
        residence_end = (
            next_departure
            if next_at_home
            else next_departure - max(int(deadhead_min), 0)
        )
        if residence_end <= residence_start:
            return None
        return residence_start, residence_end

    def _connection_deadhead_interval(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        previous_trip: ProblemTrip,
        next_trip: ProblemTrip,
        *,
        deadhead_min: int,
    ) -> Tuple[int, int]:
        """Place deadhead travel consistently with the depot-residence policy."""
        duration = max(int(deadhead_min), 0)
        next_departure = self._service_minute(
            problem, int(next_trip.departure_min)
        )
        home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "")
        next_at_home = self._locations_equivalent(
            problem, next_trip.origin, home_depot_id
        )
        if next_at_home:
            start = (
                self._trip_service_arrival_min(problem, previous_trip)
                + self._turnaround_min(problem, previous_trip.destination)
            )
            return start, start + duration
        return next_departure - duration, next_departure

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

    def _metadata_truthy(self, value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

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

