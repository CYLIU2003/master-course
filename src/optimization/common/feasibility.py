from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

from src.dispatch.feasibility import FeasibilityEngine, evaluate_startup_feasibility
from src.dispatch.models import ValidationResult, VehicleDuty
from src.dispatch.route_band import (
    duty_route_band_ids,
    fragment_transition_diagnostic,
    fragment_transition_is_feasible,
)
from src.dispatch.validator import DutyValidator

from .problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    day_index_for_minute,
    normalize_service_coverage_mode,
)
from .bess_terminal_policy import resolve_bess_terminal_soc_target_kwh
from .bev_terminal_policy import (
    BevTerminalSocPolicy,
    normalize_bev_terminal_soc_policy,
)
from .time_axis import chronological_duty_key, service_minute
from .soc_helpers import (
    deadhead_before_trip_energy_kwh,
    effective_final_soc_target_kwh,
    final_soc_floor_kwh,
    final_soc_target_enabled,
    post_return_target_slot_index,
    remaining_posted_transition_fraction,
    return_deadhead_energy_kwh,
    return_deadhead_min_to_home,
    required_departure_soc_kwh,
    slot_index_ceil,
    trip_active_in_slot,
    trip_active_slot_indices,
    trip_energy_kwh,
    trip_slot_energy_fraction,
)


@dataclass(frozen=True)
class FeasibilityReport:
    feasible: bool
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    invalid_duties: tuple[str, ...] = ()
    uncovered_trip_ids: tuple[str, ...] = ()
    duplicate_trip_ids: tuple[str, ...] = ()
    validation: Dict[str, ValidationResult] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[Dict[str, Any], ...] = ()


class FeasibilityChecker:
    def __init__(self) -> None:
        self._validator = DutyValidator()
        self._connection_engine = FeasibilityEngine()

    def evaluate(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> FeasibilityReport:
        eligible_trip_ids = set(problem.eligible_trip_ids())
        service_coverage_mode = normalize_service_coverage_mode(
            getattr(problem.scenario, "service_coverage_mode", None)
            or problem.metadata.get("service_coverage_mode", "strict")
        )
        assigned_trip_ids: List[str] = []
        validation: Dict[str, ValidationResult] = {}
        errors: List[str] = []
        warnings: List[str] = []

        for duty in plan.duties:
            result = self._validator.validate_vehicle_duty(
                duty,
                problem.dispatch_context,
            )
            validation[duty.duty_id] = result
            assigned_trip_ids.extend(duty.trip_ids)
            if not result.valid:
                for message in result.errors:
                    errors.append(f"[{duty.duty_id}] {message}")

        seen: set[str] = set()
        duplicates: List[str] = []
        for trip_id in assigned_trip_ids:
            if trip_id in seen:
                duplicates.append(trip_id)
            seen.add(trip_id)

        uncovered = sorted(eligible_trip_ids - set(assigned_trip_ids))
        if uncovered:
            uncovered_message = "Uncovered trips: " + ", ".join(uncovered)
            if service_coverage_mode == "penalized":
                warnings.append(uncovered_message)
            else:
                errors.append(
                    f"strict coverage violated with {len(uncovered)} uncovered trips: "
                    + ", ".join(uncovered)
                )
        if duplicates:
            errors.append(
                "Duplicate trip assignments: " + ", ".join(sorted(set(duplicates)))
            )

        invalid_duties = tuple(
            duty_id for duty_id, result in validation.items() if not result.valid
        )

        errors.extend(self._evaluate_vehicle_fragment_integrity(problem, plan))
        errors.extend(self._evaluate_vehicle_availability(problem, plan))
        errors.extend(self._evaluate_route_band_integrity(problem, plan))
        errors.extend(self._evaluate_startup_deadhead(problem, plan))

        soc_errors = self._evaluate_soc(problem, plan)
        errors.extend(soc_errors)
        metrics = self._build_validation_metrics(
            problem,
            plan,
            uncovered_trip_ids=uncovered,
            duplicate_trip_ids=duplicates,
            soc_errors=soc_errors,
        )
        errors.extend(self._metric_errors(metrics))
        diagnostics = self._build_assignment_diagnostics(
            problem,
            plan,
            uncovered_trip_ids=uncovered,
        )

        # Unserved trips are only soft when partial service is explicitly allowed.
        feasible = not errors and self._metrics_are_clean(metrics)
        return FeasibilityReport(
            feasible=feasible,
            warnings=tuple(warnings),
            errors=tuple(errors),
            invalid_duties=invalid_duties,
            uncovered_trip_ids=tuple(uncovered),
            duplicate_trip_ids=tuple(sorted(set(duplicates))),
            validation=validation,
            metrics=metrics,
            diagnostics=diagnostics,
        )

    def _build_assignment_diagnostics(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
        *,
        uncovered_trip_ids: List[str],
    ) -> tuple[Dict[str, Any], ...]:
        """Return machine-readable reasons a solver candidate fails dispatch checks.

        This uses the same ``FeasibilityEngine.can_connect`` call as graph/arc
        generation and duty validation.  It is intentionally a report only: a
        research run must reject an invalid incumbent instead of repairing it.
        """
        diagnostics: List[Dict[str, Any]] = []
        duty_vehicle_map = plan.duty_vehicle_map()
        vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}

        for trip_id in sorted(set(uncovered_trip_ids)):
            diagnostics.append(
                {
                    "kind": "uncovered_trip",
                    "trip_id": str(trip_id),
                    "vehicle_id": None,
                    "previous_trip_id": None,
                    "next_trip_id": None,
                    "rejection_reason": "trip_not_present_in_exported_vehicle_duties",
                }
            )

        for duty in plan.duties:
            vehicle_id = str(duty_vehicle_map.get(duty.duty_id) or duty.duty_id)
            vehicle = vehicle_by_id.get(vehicle_id)
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "")
            for previous_leg, next_leg in zip(duty.legs, duty.legs[1:]):
                result = self._connection_engine.can_connect(
                    previous_leg.trip,
                    next_leg.trip,
                    problem.dispatch_context,
                    duty.vehicle_type,
                )
                if result.feasible:
                    continue
                diagnostics.append(
                    {
                        "kind": "trip_connection",
                        "vehicle_id": vehicle_id,
                        "home_depot_id": home_depot_id,
                        "duty_id": str(duty.duty_id),
                        "previous_trip_id": str(previous_leg.trip.trip_id),
                        "next_trip_id": str(next_leg.trip.trip_id),
                        "deadhead_time_min": int(result.deadhead_time_min or 0),
                        "turnaround_time_min": int(result.turnaround_time_min or 0),
                        "slack_min": result.slack_min,
                        "rejection_reason_code": str(result.reason_code),
                        "rejection_reason": str(result.reason),
                    }
                )

            if duty.legs and vehicle is not None:
                startup = evaluate_startup_feasibility(
                    duty.legs[0].trip,
                    problem.dispatch_context,
                    home_depot_id,
                )
                if not startup.feasible:
                    diagnostics.append(
                        {
                            "kind": "startup",
                            "vehicle_id": vehicle_id,
                            "home_depot_id": home_depot_id,
                            "duty_id": str(duty.duty_id),
                            "previous_trip_id": None,
                            "next_trip_id": str(duty.legs[0].trip.trip_id),
                            "deadhead_time_min": int(startup.deadhead_time_min or 0),
                            "turnaround_time_min": int(startup.turnaround_time_min or 0),
                            "slack_min": startup.slack_min,
                            "rejection_reason_code": str(startup.reason_code),
                            "rejection_reason": str(startup.reason),
                        }
                    )

        fixed_route_band_mode = bool((problem.metadata or {}).get("fixed_route_band_mode", False))
        allow_same_day_depot_cycles = bool(
            getattr(problem.scenario, "allow_same_day_depot_cycles", True)
        )
        for vehicle_id, duties in plan.duties_by_vehicle().items():
            ordered = sorted(
                (duty for duty in duties if duty.legs),
                key=lambda duty: chronological_duty_key(
                    duty, horizon_start_min=self._horizon_start_min(problem)
                ),
            )
            vehicle = vehicle_by_id.get(str(vehicle_id))
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "")
            for previous_duty, next_duty in zip(ordered, ordered[1:]):
                transition = fragment_transition_diagnostic(
                    previous_duty,
                    next_duty,
                    home_depot_id=home_depot_id,
                    dispatch_context=problem.dispatch_context,
                    fixed_route_band_mode=fixed_route_band_mode,
                    allow_same_day_depot_cycles=allow_same_day_depot_cycles,
                )
                if transition.feasible:
                    continue
                diagnostics.append(
                    {
                        "kind": "fragment_transition",
                        "vehicle_id": str(vehicle_id),
                        "home_depot_id": home_depot_id,
                        "duty_id": str(next_duty.duty_id),
                        "previous_duty_id": str(previous_duty.duty_id),
                        "previous_trip_id": str(previous_duty.legs[-1].trip.trip_id),
                        "next_trip_id": str(next_duty.legs[0].trip.trip_id),
                        "rejection_reason_code": str(transition.reason_code),
                        "rejection_reason": (
                            "Fragment transition rejected by the shared "
                            f"depot/direct-connectivity rule: {transition.reason_code}"
                        ),
                    }
                )

        return tuple(diagnostics)

    def _build_validation_metrics(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
        *,
        uncovered_trip_ids: List[str],
        duplicate_trip_ids: List[str],
        soc_errors: List[str],
    ) -> Dict[str, Any]:
        ev_soc_bounds = self._count_vehicle_soc_bound_violations(problem, plan)
        bess_metrics = self._evaluate_bess_metrics(problem, plan)
        metrics: Dict[str, Any] = {
            "unassigned_trip_count": int(len(set(uncovered_trip_ids))),
            "duplicate_trip_count": int(len(set(duplicate_trip_ids))),
            "vehicle_time_overlap_count": self._count_vehicle_time_overlaps(problem, plan),
            "infeasible_transition_count": self._count_infeasible_transitions(problem, plan),
            "ev_soc_lower_violation_count": int(ev_soc_bounds["lower"]),
            "ev_soc_upper_violation_count": int(ev_soc_bounds["upper"]),
            "ev_soc_violation_count": int(len(soc_errors) + ev_soc_bounds["lower"] + ev_soc_bounds["upper"]),
            "bess_soc_lower_violation_count": int(bess_metrics["lower"]),
            "bess_soc_upper_violation_count": int(bess_metrics["upper"]),
            "bess_soc_violation_count": int(bess_metrics["lower"] + bess_metrics["upper"]),
            "bess_terminal_soc_deviation_kwh": float(bess_metrics["terminal_deviation_kwh"]),
            "bess_terminal_soc_tolerance_kwh": float(bess_metrics["terminal_tolerance_kwh"]),
            "contract_power_violation_count": self._count_contract_power_violations(problem, plan),
            "charger_concurrency_violation_count": self._count_charger_concurrency_violations(problem, plan),
        }
        metrics["all_required_validation_checks_passed"] = self._metrics_are_clean(metrics)
        return metrics

    def _metric_errors(self, metrics: Mapping[str, Any]) -> List[str]:
        checks = {
            "unassigned_trip_count": "unassigned trips remain",
            "vehicle_time_overlap_count": "vehicle time overlaps remain",
            "infeasible_transition_count": "infeasible vehicle transitions remain",
            "ev_soc_violation_count": "EV SOC bound/readiness violations remain",
            "bess_soc_violation_count": "BESS SOC bound violations remain",
            "contract_power_violation_count": "contract power violations remain",
            "charger_concurrency_violation_count": "charger concurrency violations remain",
        }
        errors: List[str] = []
        for key, label in checks.items():
            if int(metrics.get(key, 0) or 0) > 0:
                errors.append(f"[VALIDATION] {label}: {int(metrics.get(key, 0) or 0)}")
        deviation = float(metrics.get("bess_terminal_soc_deviation_kwh", 0.0) or 0.0)
        tolerance = float(metrics.get("bess_terminal_soc_tolerance_kwh", 0.0) or 0.0)
        if deviation > tolerance + 1.0e-9:
            errors.append(
                f"[VALIDATION] BESS terminal SOC deviation {deviation:.6f} kWh exceeds tolerance {tolerance:.6f} kWh"
            )
        return errors

    def _metrics_are_clean(self, metrics: Mapping[str, Any]) -> bool:
        required_zero_keys = (
            "unassigned_trip_count",
            "vehicle_time_overlap_count",
            "infeasible_transition_count",
            "ev_soc_violation_count",
            "bess_soc_violation_count",
            "contract_power_violation_count",
            "charger_concurrency_violation_count",
        )
        if any(int(metrics.get(key, 0) or 0) != 0 for key in required_zero_keys):
            return False
        deviation = float(metrics.get("bess_terminal_soc_deviation_kwh", 0.0) or 0.0)
        tolerance = float(metrics.get("bess_terminal_soc_tolerance_kwh", 0.0) or 0.0)
        return deviation <= tolerance + 1.0e-9

    def _count_vehicle_time_overlaps(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> int:
        overlap_count = 0
        for _vehicle_id, duties in plan.duties_by_vehicle().items():
            intervals: List[tuple[int, int]] = []
            for duty in duties:
                for leg in duty.legs:
                    start_min = service_minute(
                        leg.trip.departure_min,
                        horizon_start_min=self._horizon_start_min(problem),
                    )
                    end_min = service_minute(
                        leg.trip.arrival_min,
                        horizon_start_min=self._horizon_start_min(problem),
                    )
                    if end_min < start_min:
                        end_min += 24 * 60
                    intervals.append((start_min, end_min))
            intervals.sort()
            previous_end = None
            for start_min, end_min in intervals:
                if previous_end is not None and start_min < previous_end:
                    overlap_count += 1
                previous_end = max(previous_end or end_min, end_min)
        return overlap_count

    def _count_infeasible_transitions(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> int:
        count = 0
        for duty in plan.duties:
            for idx in range(len(duty.legs) - 1):
                result = self._connection_engine.can_connect(
                    duty.legs[idx].trip,
                    duty.legs[idx + 1].trip,
                    problem.dispatch_context,
                    duty.vehicle_type,
                )
                if not result.feasible:
                    count += 1
        return count

    def _count_vehicle_soc_bound_violations(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> Dict[str, int]:
        lower = 0
        upper = 0
        vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
        type_by_id = {str(vtype.vehicle_type_id): vtype for vtype in problem.vehicle_types}
        for vehicle_id, slot_map in (plan.vehicle_soc_kwh_by_vehicle_slot or {}).items():
            vehicle = vehicle_by_id.get(str(vehicle_id))
            vtype = type_by_id.get(str(getattr(vehicle, "vehicle_type", "") or "")) if vehicle is not None else None
            capacity = float(
                (getattr(vehicle, "battery_capacity_kwh", None) if vehicle is not None else None)
                or (getattr(vtype, "battery_capacity_kwh", None) if vtype is not None else None)
                or 0.0
            )
            if capacity <= 0.0:
                continue
            reserve = getattr(vehicle, "reserve_soc", None) if vehicle is not None else None
            if reserve is None and vtype is not None:
                reserve = getattr(vtype, "reserve_soc", None)
            soc_min = 0.15 * capacity if reserve is None else (float(reserve) * capacity if float(reserve) <= 1.0 else float(reserve))
            for value in dict(slot_map or {}).values():
                soc = float(value or 0.0)
                if soc + 1.0e-6 < soc_min:
                    lower += 1
                if soc > capacity + 1.0e-6:
                    upper += 1
        return {"lower": lower, "upper": upper}

    def _evaluate_bess_metrics(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> Dict[str, float | int]:
        lower = 0
        upper = 0
        terminal_deviation = 0.0
        tolerance = float((problem.metadata or {}).get("bess_terminal_soc_tolerance_kwh", 1.0e-6) or 1.0e-6)
        assets = dict(getattr(problem, "depot_energy_assets", {}) or {})
        timestep_slots = sorted({int(slot.slot_index) for slot in list(getattr(problem, "price_slots", ()) or ())})
        for depot_id, asset in assets.items():
            if not bool(getattr(asset, "bess_enabled", False)):
                continue
            max_soc = max(float(getattr(asset, "bess_soc_max_kwh", 0.0) or 0.0), 0.0)
            capacity = max(float(getattr(asset, "bess_energy_kwh", 0.0) or 0.0), 0.0)
            if max_soc <= 0.0:
                max_soc = capacity
            if max_soc <= 0.0:
                continue
            min_soc = min(max(float(getattr(asset, "bess_soc_min_kwh", 0.0) or 0.0), 0.0), max_soc)
            soc = min(max(float(getattr(asset, "bess_initial_soc_kwh", 0.0) or 0.0), min_soc), max_soc)
            charge_eff = max(float(getattr(asset, "bess_charge_efficiency", 0.95) or 0.95), 1.0e-9)
            discharge_eff = max(float(getattr(asset, "bess_discharge_efficiency", 0.95) or 0.95), 1.0e-9)
            depot_key = str(depot_id)
            slot_indices = set(timestep_slots)
            for mapping in (
                plan.pv_to_bess_kwh_by_depot_slot,
                plan.grid_to_bess_kwh_by_depot_slot,
                plan.bess_to_bus_kwh_by_depot_slot,
            ):
                slot_indices.update(int(slot_idx) for slot_idx in dict(mapping or {}).get(depot_key, {}).keys())
            for slot_idx in sorted(slot_indices):
                if soc + 1.0e-6 < min_soc:
                    lower += 1
                if soc > max_soc + 1.0e-6:
                    upper += 1
                charge_in = float(dict(plan.pv_to_bess_kwh_by_depot_slot or {}).get(depot_key, {}).get(slot_idx, 0.0) or 0.0)
                charge_in += float(dict(plan.grid_to_bess_kwh_by_depot_slot or {}).get(depot_key, {}).get(slot_idx, 0.0) or 0.0)
                discharge = float(dict(plan.bess_to_bus_kwh_by_depot_slot or {}).get(depot_key, {}).get(slot_idx, 0.0) or 0.0)
                soc = soc + charge_eff * max(charge_in, 0.0) - max(discharge, 0.0) / discharge_eff
                if soc + 1.0e-6 < min_soc:
                    lower += 1
                if soc > max_soc + 1.0e-6:
                    upper += 1
            terminal_min = min(max(float(getattr(asset, "bess_terminal_soc_min_kwh", 0.0) or 0.0), min_soc), max_soc)
            terminal_target = resolve_bess_terminal_soc_target_kwh(
                policy=getattr(asset, "bess_terminal_soc_policy", ""),
                initial_soc_kwh=float(
                    getattr(asset, "bess_initial_soc_kwh", 0.0) or 0.0
                ),
                configured_target_kwh=float(
                    getattr(asset, "bess_terminal_soc_target_kwh", 0.0) or 0.0
                ),
                terminal_soc_floor_kwh=terminal_min,
                maximum_soc_kwh=max_soc,
            )
            if terminal_target is not None:
                terminal_deviation = max(terminal_deviation, abs(soc - terminal_target))
            else:
                terminal_deviation = max(terminal_deviation, max(terminal_min - soc, 0.0))
        return {
            "lower": lower,
            "upper": upper,
            "terminal_deviation_kwh": terminal_deviation,
            "terminal_tolerance_kwh": tolerance,
        }

    def _count_contract_power_violations(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> int:
        timestep_h = max(float(getattr(problem.scenario, "timestep_min", 0) or 0.0), 1.0) / 60.0
        depot_limit_by_id = {
            str(getattr(depot, "depot_id", "") or ""): float(getattr(depot, "import_limit_kw", 0.0) or 0.0)
            for depot in list(getattr(problem, "depots", ()) or ())
            if str(getattr(depot, "depot_id", "") or "")
        }
        depot_ids = set(depot_limit_by_id)
        depot_ids.update(str(key) for key in dict(plan.grid_to_bus_kwh_by_depot_slot or {}).keys())
        depot_ids.update(str(key) for key in dict(plan.grid_to_bess_kwh_by_depot_slot or {}).keys())
        violations = 0
        for depot_id in depot_ids:
            limit_kw = max(float(depot_limit_by_id.get(depot_id, 0.0) or 0.0), 0.0)
            if limit_kw <= 0.0:
                continue
            slot_indices = set(dict(plan.grid_to_bus_kwh_by_depot_slot or {}).get(depot_id, {}).keys())
            slot_indices.update(dict(plan.grid_to_bess_kwh_by_depot_slot or {}).get(depot_id, {}).keys())
            for slot_idx in slot_indices:
                grid_kwh = float(dict(plan.grid_to_bus_kwh_by_depot_slot or {}).get(depot_id, {}).get(slot_idx, 0.0) or 0.0)
                grid_kwh += float(dict(plan.grid_to_bess_kwh_by_depot_slot or {}).get(depot_id, {}).get(slot_idx, 0.0) or 0.0)
                if grid_kwh > limit_kw * timestep_h + 1.0e-6:
                    violations += 1
        return violations

    def _count_charger_concurrency_violations(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> int:
        if not problem.chargers:
            return 0
        ports_by_depot: Dict[str, int] = {}
        charger_by_id = {}
        for charger in problem.chargers:
            depot_id = str(getattr(charger, "depot_id", "") or "depot_default")
            ports_by_depot[depot_id] = ports_by_depot.get(depot_id, 0) + max(int(getattr(charger, "simultaneous_ports", 1) or 1), 1)
            charger_by_id[str(charger.charger_id)] = charger
        vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
        vehicle_home = {vehicle_id: str(vehicle.home_depot_id or "depot_default") for vehicle_id, vehicle in vehicle_by_id.items()}
        active: Dict[tuple[str, int], set[str]] = {}
        active_by_charger: Dict[tuple[str, int], set[str]] = {}
        power_by_vehicle_charger_slot: Dict[tuple[str, str, int], float] = {}
        violations = 0
        for slot in plan.charging_slots:
            charge_kw = max(float(getattr(slot, "charge_kw", 0.0) or 0.0), 0.0)
            if charge_kw <= 1.0e-9:
                continue
            vehicle_id = str(getattr(slot, "vehicle_id", "") or "")
            depot_id = str(getattr(slot, "charging_depot_id", "") or vehicle_home.get(vehicle_id) or "depot_default")
            slot_idx = int(getattr(slot, "slot_index", 0) or 0)
            active.setdefault((depot_id, slot_idx), set()).add(vehicle_id)
            charger_id = str(getattr(slot, "charger_id", "") or "")
            charger = charger_by_id.get(charger_id)
            if charger is None:
                # Legacy artifacts encode energy source in charger_id.  The
                # depot-level fallback remains auditable but cannot prove
                # charger-type compatibility.
                continue
            active_by_charger.setdefault((charger_id, slot_idx), set()).add(vehicle_id)
            key = (vehicle_id, charger_id, slot_idx)
            power_by_vehicle_charger_slot[key] = (
                power_by_vehicle_charger_slot.get(key, 0.0) + charge_kw
            )
            if str(charger.depot_id or "depot_default") != depot_id:
                violations += 1
            vehicle = vehicle_by_id.get(vehicle_id)
            explicit_ids = tuple(
                getattr(vehicle, "compatible_charger_ids", ()) or ()
            ) if vehicle is not None else ()
            if explicit_ids and charger_id not in explicit_ids:
                violations += 1
        for (depot_id, _slot_idx), vehicle_ids in active.items():
            if len(vehicle_ids) > ports_by_depot.get(depot_id, 0):
                violations += 1
        for (charger_id, _slot_idx), vehicle_ids in active_by_charger.items():
            charger = charger_by_id[charger_id]
            ports = max(int(charger.simultaneous_ports or 1), 1)
            if len(vehicle_ids) > ports:
                violations += 1
        for (vehicle_id, charger_id, _slot_idx), charge_kw in power_by_vehicle_charger_slot.items():
            charger = charger_by_id[charger_id]
            vehicle = vehicle_by_id.get(vehicle_id)
            vehicle_limit = getattr(vehicle, "charge_power_max_kw", None)
            if vehicle_limit is None and vehicle is not None:
                vehicle_type = next(
                    (
                        item
                        for item in problem.vehicle_types
                        if item.vehicle_type_id == vehicle.vehicle_type
                    ),
                    None,
                )
                vehicle_limit = getattr(vehicle_type, "charge_power_max_kw", None)
            limit_kw = max(float(charger.power_kw or 0.0), 0.0)
            if vehicle_limit is not None:
                limit_kw = min(limit_kw, max(float(vehicle_limit), 0.0))
            if charge_kw > limit_kw + 1.0e-6:
                violations += 1
        return violations

    def _evaluate_soc(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> List[str]:
        errors: List[str] = []
        if not plan.duties:
            return errors

        trip_by_id = problem.trip_by_id()
        vehicle_by_id = {v.vehicle_id: v for v in problem.vehicles}
        type_by_id = {vt.vehicle_type_id: vt for vt in problem.vehicle_types}
        dt_h = max(problem.scenario.timestep_min, 1) / 60.0
        duty_vehicle_map = plan.duty_vehicle_map()
        target_enabled = final_soc_target_enabled(problem)
        horizon_start_min = self._horizon_start_min(problem)
        rolling_start_slot_raw = (plan.metadata or {}).get(
            "rolling_start_slot_index"
        )
        rolling_start_slot = (
            int(rolling_start_slot_raw)
            if rolling_start_slot_raw is not None
            else None
        )
        rolling_start_abs_min = (
            horizon_start_min
            + rolling_start_slot * max(problem.scenario.timestep_min, 1)
            if rolling_start_slot is not None
            else None
        )

        charge_by_vehicle: Dict[str, Dict[int, float]] = {}
        for slot in plan.charging_slots:
            vid = str(slot.vehicle_id)
            by_slot = charge_by_vehicle.setdefault(vid, {})
            by_slot[int(slot.slot_index)] = by_slot.get(int(slot.slot_index), 0.0) + max(float(slot.charge_kw or 0.0), 0.0)

        last_duty_by_vehicle_day: Dict[tuple[str, int], str] = {}
        if target_enabled:
            for duty in plan.duties:
                if not duty.legs:
                    continue
                vehicle_id = str(duty_vehicle_map.get(duty.duty_id, duty.duty_id))
                day_idx = day_index_for_minute(int(duty.legs[-1].trip.departure_min), horizon_start_min)
                key = (vehicle_id, day_idx)
                incumbent_id = last_duty_by_vehicle_day.get(key)
                if incumbent_id is None:
                    last_duty_by_vehicle_day[key] = str(duty.duty_id)
                    continue
                incumbent = next((item for item in plan.duties if str(item.duty_id) == incumbent_id), None)
                incumbent_end = int(incumbent.legs[-1].trip.arrival_min) if incumbent and incumbent.legs else -1
                if int(duty.legs[-1].trip.arrival_min) >= incumbent_end:
                    last_duty_by_vehicle_day[key] = str(duty.duty_id)

        for duty in plan.duties:
            vehicle_id = str(duty_vehicle_map.get(duty.duty_id, duty.duty_id))
            vehicle = vehicle_by_id.get(vehicle_id)
            vtype = type_by_id.get(duty.vehicle_type)
            powertrain = str((vtype.powertrain_type if vtype else duty.vehicle_type) or "").upper()
            if powertrain not in {"BEV", "PHEV", "FCEV"}:
                continue

            capacity = float(
                (vehicle.battery_capacity_kwh if vehicle else None)
                or (vtype.battery_capacity_kwh if vtype else 0.0)
                or 0.0
            )
            if capacity <= 0.0:
                continue

            reserve = float(
                (vehicle.reserve_soc if vehicle else None)
                or (vtype.reserve_soc if vtype else None)
                or (0.15 * capacity)
            )
            soc = float((vehicle.initial_soc if vehicle else None) or (0.8 * capacity))
            if soc <= 1.0:
                soc = soc * capacity
            soc = min(max(soc, 0.0), capacity)

            active_legs: List[tuple[int, object, object, tuple[int, ...]]] = []
            for duty_leg_index, leg in enumerate(duty.legs):
                trip = trip_by_id.get(leg.trip.trip_id)
                if trip is None:
                    continue
                slots = trip_active_slot_indices(problem, trip.departure_min, trip.arrival_min)
                if rolling_start_slot is not None:
                    slots = tuple(
                        slot_idx
                        for slot_idx in slots
                        if slot_idx >= rolling_start_slot
                    )
                if not slots:
                    continue
                active_legs.append((duty_leg_index, leg, trip, slots))

            if not active_legs:
                continue

            first_slot = min(
                slots[0] for _index, _leg, _trip, slots in active_legs
            )
            last_slot = max(
                slots[-1] for _index, _leg, _trip, slots in active_legs
            )
            vehicle_charges = charge_by_vehicle.get(vehicle_id, {})
            if vehicle_charges:
                first_slot = min(first_slot, min(vehicle_charges.keys()))
                last_slot = max(last_slot, max(vehicle_charges.keys()))

            target_kwh = None
            target_slot_idx = None
            return_event_slot_idx = None
            return_event_energy_kwh = 0.0
            return_event_applied = False
            day_idx = day_index_for_minute(int(duty.legs[-1].trip.departure_min), horizon_start_min)
            if (
                target_enabled
                and last_duty_by_vehicle_day.get((vehicle_id, day_idx)) == str(duty.duty_id)
            ):
                target_kwh = effective_final_soc_target_kwh(problem, vehicle, cap_kwh=capacity)
                last_problem_trip = trip_by_id.get(duty.legs[-1].trip.trip_id)
                if target_kwh is not None and last_problem_trip is not None:
                    return_exists, return_deadhead_min = return_deadhead_min_to_home(
                        problem,
                        vehicle,
                        last_problem_trip,
                    )
                    if not return_exists:
                        errors.append(
                            f"[SOC_TARGET] duty={duty.duty_id} vehicle={vehicle_id} final trip={last_problem_trip.trip_id} cannot return to home depot"
                        )
                    else:
                        return_complete_min = int(duty.legs[-1].trip.arrival_min) + int(return_deadhead_min)
                        return_event_slot_idx = slot_index_ceil(problem, return_complete_min)
                        return_event_energy_kwh = return_deadhead_energy_kwh(
                            problem,
                            vehicle,
                            last_problem_trip,
                        )
                        target_slot_idx = post_return_target_slot_index(problem, day_idx)
                        first_slot = min(first_slot, return_event_slot_idx)
                        last_slot = max(last_slot, target_slot_idx)
                else:
                    target_kwh = None

            soc_at_target_slot = None
            for slot_idx in range(first_slot, last_slot + 1):
                if (
                    return_event_slot_idx is not None
                    and not return_event_applied
                    and slot_idx >= return_event_slot_idx
                ):
                    soc -= return_event_energy_kwh
                    return_event_applied = True
                    floor_kwh = final_soc_floor_kwh(problem, vehicle, cap_kwh=capacity)
                    if soc + 1.0e-6 < floor_kwh:
                        errors.append(
                            f"[SOC_TARGET] duty={duty.duty_id} vehicle={vehicle_id} post-return SOC {soc:.2f} < floor {floor_kwh:.2f}"
                        )
                charge_kwh = max(float(vehicle_charges.get(slot_idx, 0.0) or 0.0), 0.0) * dt_h * 0.95
                if charge_kwh > 0.0 and any(
                    trip_active_in_slot(
                        problem,
                        leg.trip.departure_min,
                        leg.trip.arrival_min,
                        slot_idx,
                    )
                    for _index, leg, _trip, _slots in active_legs
                ):
                    errors.append(
                        f"[SOC] duty={duty.duty_id} vehicle={vehicle_id} charging occurs during active trip slot {slot_idx}"
                    )
                if (
                    charge_kwh > 0.0
                    and target_slot_idx is not None
                    and return_event_slot_idx is not None
                    and self._slot_index(problem, int(duty.legs[-1].trip.arrival_min))
                    <= slot_idx
                    < return_event_slot_idx
                ):
                    errors.append(
                        f"[SOC_TARGET] duty={duty.duty_id} vehicle={vehicle_id} charges before return deadhead completion at slot {slot_idx}"
                    )
                soc = min(capacity, soc + charge_kwh)

                for duty_leg_index, leg, trip, slots in active_legs:
                    if slot_idx not in slots:
                        continue
                    departure_slot = self._slot_index(
                        problem, int(trip.departure_min)
                    )
                    if slot_idx == slots[0] and slot_idx == departure_slot:
                        previous_trip = None
                        if duty_leg_index > 0:
                            previous_leg = duty.legs[duty_leg_index - 1]
                            previous_trip = trip_by_id.get(
                                previous_leg.trip.trip_id
                            )
                        deadhead_kwh = deadhead_before_trip_energy_kwh(
                            problem,
                            vehicle,
                            trip,
                            previous_trip=previous_trip,
                        )
                        if rolling_start_abs_min is not None:
                            departure_abs_min = service_minute(
                                trip.departure_min,
                                horizon_start_min=horizon_start_min,
                            )
                            deadhead_kwh *= remaining_posted_transition_fraction(
                                event_end_min=departure_abs_min,
                                rolling_start_abs_min=rolling_start_abs_min,
                            )
                        soc -= deadhead_kwh
                        if soc < -1.0e-6:
                            errors.append(
                                f"[SOC] duty={duty.duty_id} trip={trip.trip_id} deadhead-adjusted SOC {soc:.2f} < 0"
                            )
                        required = required_departure_soc_kwh(
                            problem,
                            vehicle,
                            trip,
                            cap_kwh=capacity,
                            final_soc_floor_kwh=reserve,
                        )
                        if soc + 1.0e-6 < required:
                            errors.append(
                                f"[SOC] duty={duty.duty_id} trip={trip.trip_id} departure SOC {soc:.2f} < required {required:.2f}"
                            )

                    trip_energy = trip_energy_kwh(problem, vehicle, trip)
                    fraction = trip_slot_energy_fraction(
                        problem,
                        trip.departure_min,
                        trip.arrival_min,
                        slot_idx,
                    )
                    soc -= trip_energy * fraction
                    if soc < -1.0e-6:
                        errors.append(
                            f"[SOC] duty={duty.duty_id} trip={trip.trip_id} post-slot SOC {soc:.2f} < 0"
                        )
                if target_slot_idx is not None and slot_idx == target_slot_idx:
                    soc_at_target_slot = soc

            if target_kwh is not None:
                checked_soc = soc if soc_at_target_slot is None else soc_at_target_slot
                if checked_soc + 1.0e-6 < target_kwh:
                    errors.append(
                        f"[SOC_TARGET] duty={duty.duty_id} vehicle={vehicle_id} post-return target SOC {checked_soc:.2f} < required {target_kwh:.2f}"
                    )
                terminal_policy = normalize_bev_terminal_soc_policy(
                    problem.metadata.get("bev_terminal_soc_policy"),
                    has_explicit_target=(
                        problem.metadata.get("final_soc_target_percent") is not None
                    ),
                )
                if terminal_policy is BevTerminalSocPolicy.RETURN_TO_INITIAL:
                    tolerance_kwh = max(
                        float(
                            problem.metadata.get(
                                "bev_terminal_soc_equality_tolerance_kwh", 1.0e-6
                            )
                            or 1.0e-6
                        ),
                        0.0,
                    )
                    if checked_soc > target_kwh + tolerance_kwh + 1.0e-9:
                        errors.append(
                            f"[SOC_TARGET] duty={duty.duty_id} vehicle={vehicle_id} "
                            f"post-return target SOC {checked_soc:.6f} exceeds "
                            f"return-to-initial target {target_kwh:.6f} by more than "
                            f"{tolerance_kwh:.6f} kWh"
                        )

        return errors

    def _remaining_deadhead_fraction(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle: Any,
        previous_trip: Any,
        next_trip: Any,
        *,
        rolling_start_abs_min: int,
    ) -> float:
        """Return the inter-trip deadhead share not completed at roll time."""

        context = problem.dispatch_context
        if context is None:
            return 1.0
        deadhead_min = max(
            int(
                context.get_deadhead_min(
                    previous_trip.destination,
                    next_trip.origin,
                )
                or 0
            ),
            0,
        )
        if deadhead_min <= 0:
            return 0.0

        next_departure_min = service_minute(
            next_trip.departure_min,
            horizon_start_min=self._horizon_start_min(problem),
        )
        home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "")
        next_at_home = bool(
            home_depot_id
            and context.locations_equivalent(next_trip.origin, home_depot_id)
        )
        if next_at_home:
            previous_arrival_min = service_minute(
                previous_trip.arrival_min,
                horizon_start_min=self._horizon_start_min(problem),
            )
            turnaround_min = max(
                int(context.get_turnaround_min(previous_trip.destination) or 0),
                0,
            )
            deadhead_start_min = previous_arrival_min + turnaround_min
        else:
            deadhead_start_min = next_departure_min - deadhead_min
        deadhead_end_min = deadhead_start_min + deadhead_min
        return remaining_posted_transition_fraction(
            event_end_min=deadhead_end_min,
            rolling_start_abs_min=rolling_start_abs_min,
        )

    def _evaluate_startup_deadhead(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> List[str]:
        errors: List[str] = []
        if not plan.duties:
            return errors

        vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
        duty_vehicle_map = plan.duty_vehicle_map()
        for duty in plan.duties:
            if not duty.legs:
                continue
            vehicle_id = str(duty_vehicle_map.get(duty.duty_id) or duty.duty_id)
            vehicle = vehicle_by_id.get(vehicle_id)
            if vehicle is None:
                continue
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
            first_leg = duty.legs[0]
            if not home_depot_id:
                continue
            startup_result = evaluate_startup_feasibility(
                first_leg.trip,
                problem.dispatch_context,
                home_depot_id,
            )
            required_deadhead_min = max(int(startup_result.deadhead_time_min or 0), 0)
            if not startup_result.feasible:
                errors.append(
                    f"[STARTUP] duty={duty.duty_id} vehicle={vehicle_id} "
                    f"{startup_result.reason_code}: {startup_result.reason}"
                )
                continue
            actual_deadhead_min = max(int(first_leg.deadhead_from_prev_min or 0), 0)
            if actual_deadhead_min + 1.0e-6 < required_deadhead_min:
                errors.append(
                    f"[STARTUP] duty={duty.duty_id} vehicle={vehicle_id} startup deadhead {actual_deadhead_min} < required {required_deadhead_min}"
                )
        return errors

    def _evaluate_vehicle_fragment_integrity(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> List[str]:
        errors: List[str] = []
        max_start_fragments = max(int(problem.metadata.get("max_start_fragments_per_vehicle") or 1), 1)
        max_end_fragments = max(int(problem.metadata.get("max_end_fragments_per_vehicle") or 1), 1)
        allow_same_day_depot_cycles = bool(
            getattr(problem.scenario, "allow_same_day_depot_cycles", True)
            if getattr(problem.scenario, "allow_same_day_depot_cycles", None) is not None
            else problem.metadata.get("allow_same_day_depot_cycles", True)
        )
        max_depot_cycles_per_vehicle_per_day = max(
            int(
                getattr(problem.scenario, "max_depot_cycles_per_vehicle_per_day", None)
                or problem.metadata.get("max_depot_cycles_per_vehicle_per_day", 1)
                or 1
            ),
            1,
        )
        if not allow_same_day_depot_cycles:
            max_depot_cycles_per_vehicle_per_day = 1
        horizon_start_min = self._horizon_start_min(problem)
        fixed_route_band_mode = bool((problem.metadata or {}).get("fixed_route_band_mode", False))
        duties_by_vehicle = plan.duties_by_vehicle()
        for vehicle_id, duties in duties_by_vehicle.items():
            fragment_count = len(duties)
            if fragment_count > max_start_fragments:
                errors.append(
                    f"[FRAGMENT] vehicle={vehicle_id} fragment_count={fragment_count} exceeds max_start_fragments_per_vehicle={max_start_fragments}"
                )
            if fragment_count > max_end_fragments:
                errors.append(
                    f"[FRAGMENT] vehicle={vehicle_id} fragment_count={fragment_count} exceeds max_end_fragments_per_vehicle={max_end_fragments}"
                )
            day_start_counts: Dict[int, int] = {}
            day_end_counts: Dict[int, int] = {}
            day_fragment_counts: Dict[int, int] = {}
            for duty in duties:
                if not duty.legs:
                    continue
                start_day = day_index_for_minute(int(duty.legs[0].trip.departure_min), horizon_start_min)
                end_day = day_index_for_minute(int(duty.legs[-1].trip.arrival_min), horizon_start_min)
                day_start_counts[start_day] = day_start_counts.get(start_day, 0) + 1
                day_end_counts[end_day] = day_end_counts.get(end_day, 0) + 1
                day_fragment_counts[start_day] = day_fragment_counts.get(start_day, 0) + 1
            for day_idx in sorted(set(day_start_counts) | set(day_end_counts)):
                start_count = int(day_start_counts.get(day_idx, 0))
                end_count = int(day_end_counts.get(day_idx, 0))
                fragment_count = int(day_fragment_counts.get(day_idx, 0))
                if start_count > max_depot_cycles_per_vehicle_per_day:
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} day={day_idx} start_fragment_count={start_count} exceeds max_depot_cycles_per_vehicle_per_day={max_depot_cycles_per_vehicle_per_day}"
                    )
                if end_count > max_depot_cycles_per_vehicle_per_day:
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} day={day_idx} end_fragment_count={end_count} exceeds max_depot_cycles_per_vehicle_per_day={max_depot_cycles_per_vehicle_per_day}"
                    )
                if fragment_count > max_depot_cycles_per_vehicle_per_day:
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} day={day_idx} fragment_count={fragment_count} exceeds max_depot_cycles_per_vehicle_per_day={max_depot_cycles_per_vehicle_per_day}"
                    )
            ordered = sorted(
                duties,
                key=lambda duty: chronological_duty_key(
                    duty, horizon_start_min=self._horizon_start_min(problem)
                ),
            )
            vehicle = next(
                (
                    candidate
                    for candidate in problem.vehicles
                    if str(candidate.vehicle_id) == str(vehicle_id)
                ),
                None,
            )
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
            for index, prev_duty in enumerate(ordered):
                for next_duty in ordered[index + 1 :]:
                    if not self._duties_overlap_in_time(
                        prev_duty,
                        next_duty,
                        horizon_start_min=self._horizon_start_min(problem),
                    ):
                        break
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} has overlapping fragments {prev_duty.duty_id} and {next_duty.duty_id}"
                    )
            for prev_duty, next_duty in zip(ordered, ordered[1:]):
                transition = fragment_transition_diagnostic(
                    prev_duty,
                    next_duty,
                    home_depot_id=home_depot_id,
                    dispatch_context=problem.dispatch_context,
                    fixed_route_band_mode=fixed_route_band_mode,
                    allow_same_day_depot_cycles=allow_same_day_depot_cycles,
                )
                if transition.feasible:
                    continue
                if allow_same_day_depot_cycles:
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} transition_reason={transition.reason_code} lacks direct-or-depot transition feasibility between {prev_duty.duty_id} and {next_duty.duty_id}"
                    )
                else:
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} transition_reason={transition.reason_code} lacks direct connection and same-day depot cycles are disabled between {prev_duty.duty_id} and {next_duty.duty_id}"
                    )
        return errors

    def _evaluate_vehicle_availability(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> List[str]:
        errors: List[str] = []
        vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
        for vehicle_id, duties in plan.duties_by_vehicle().items():
            vehicle = vehicle_by_id.get(str(vehicle_id))
            if vehicle is not None and not bool(getattr(vehicle, "available", True)):
                errors.append(
                    f"[AVAILABILITY] unavailable vehicle={vehicle_id} has {len(duties)} assigned duties"
                )
        return errors

    def _evaluate_route_band_integrity(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> List[str]:
        if not bool((problem.metadata or {}).get("fixed_route_band_mode", False)):
            return []
        errors: List[str] = []
        duties_by_vehicle = plan.duties_by_vehicle()
        horizon_start_min = self._horizon_start_min(problem)
        allow_same_day_depot_cycles = bool(
            getattr(problem.scenario, "allow_same_day_depot_cycles", True)
            if getattr(problem.scenario, "allow_same_day_depot_cycles", None) is not None
            else problem.metadata.get("allow_same_day_depot_cycles", True)
        )
        for duty in plan.duties:
            duty_bands = duty_route_band_ids(duty)
            if len(duty_bands) > 1:
                errors.append(
                    f"[ROUTE_BAND] duty={duty.duty_id} spans multiple route bands {list(duty_bands)}"
                )
        for vehicle_id, duties in duties_by_vehicle.items():
            ordered = sorted(
                duties,
                key=lambda duty: chronological_duty_key(
                    duty, horizon_start_min=self._horizon_start_min(problem)
                ),
            )
            for prev_duty, next_duty in zip(ordered, ordered[1:]):
                prev_band = duty_route_band_ids(prev_duty)
                next_band = duty_route_band_ids(next_duty)
                if not prev_band or not next_band or prev_band == next_band:
                    continue
                prev_day = day_index_for_minute(
                    int(prev_duty.legs[0].trip.departure_min),
                    horizon_start_min,
                )
                next_day = day_index_for_minute(
                    int(next_duty.legs[0].trip.departure_min),
                    horizon_start_min,
                )
                if prev_day != next_day:
                    continue
                if allow_same_day_depot_cycles:
                    errors.append(
                        f"[ROUTE_BAND] vehicle={vehicle_id} changes route band within day {prev_day} from {list(prev_band)} to {list(next_band)}"
                    )
                else:
                    errors.append(
                        f"[ROUTE_BAND] vehicle={vehicle_id} changes route band within day {prev_day} from {list(prev_band)} to {list(next_band)} while same-day depot cycles are disabled"
                    )
        return errors

    def _horizon_start_min(self, problem: CanonicalOptimizationProblem) -> int:
        start = str(getattr(problem.scenario, "horizon_start", "") or "").strip()
        if not start:
            return 0
        try:
            hh_text, mm_text = start.split(":", 1)
            return int(hh_text) * 60 + int(mm_text)
        except ValueError:
            return 0

    def _duties_overlap_in_time(
        self,
        duty_a: VehicleDuty,
        duty_b: VehicleDuty,
        *,
        horizon_start_min: int = 0,
    ) -> bool:
        for leg_a in duty_a.legs:
            start_a = service_minute(
                leg_a.trip.departure_min, horizon_start_min=horizon_start_min
            )
            end_a = service_minute(
                leg_a.trip.arrival_min, horizon_start_min=horizon_start_min
            )
            if end_a < start_a:
                end_a += 24 * 60
            for leg_b in duty_b.legs:
                start_b = service_minute(
                    leg_b.trip.departure_min, horizon_start_min=horizon_start_min
                )
                end_b = service_minute(
                    leg_b.trip.arrival_min, horizon_start_min=horizon_start_min
                )
                if end_b < start_b:
                    end_b += 24 * 60
                if start_a < end_b and start_b < end_a:
                    return True
        return False

    def _slot_index(self, problem: CanonicalOptimizationProblem, minute: int) -> int:
        step = max(problem.scenario.timestep_min, 1)
        start = 0
        if problem.scenario.horizon_start:
            try:
                hh, mm = problem.scenario.horizon_start.split(":", 1)
                start = int(hh) * 60 + int(mm)
            except ValueError:
                start = 0
        m = int(minute)
        if m < start:
            m += 24 * 60
        return max((m - start) // step, 0)

    def _deadhead_energy_kwh(self, problem: CanonicalOptimizationProblem, deadhead_min: int, trip: object) -> float:
        if deadhead_min <= 0:
            return 0.0
        speed = 18.0
        try:
            speed = float((problem.metadata or {}).get("deadhead_speed_kmh") or 18.0)
        except (TypeError, ValueError):
            speed = 18.0
        dist_km = max(float(deadhead_min), 0.0) * max(speed, 0.0) / 60.0
        trip_dist = max(float(getattr(trip, "distance_km", 0.0) or 0.0), 1.0e-6)
        per_km = max(float(getattr(trip, "energy_kwh", 0.0) or 0.0), 0.0) / trip_dist
        return max(dist_km * per_km, 0.0)
