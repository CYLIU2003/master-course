"""Check BEV targets on executed SOC boundaries, not look-ahead inventories."""
from __future__ import annotations

import math

from .bev_terminal_policy import (
    BevTerminalSocPolicy,
    bev_terminal_numeric_acceptance_contract,
    normalize_bev_terminal_soc_policy,
)
from .problem import AssignmentPlan, CanonicalOptimizationProblem
from .soc_helpers import (
    effective_final_soc_target_kwh,
    final_soc_floor_kwh,
    is_electric_vehicle,
    vehicle_initial_soc_kwh,
    vehicle_maximum_soc_kwh,
)
from .vehicle_timeline import build_vehicle_timeline, fixed_path_soc_target_slots


def audit_executed_bev_targets(
    problem: CanonicalOptimizationProblem, plan: AssignmentPlan,
) -> dict:
    """Apply the original evaluation policy to the stitched execution trace.

    A fixed target is a lower bound; only return_to_initial adds an upper
    equality band. A rolling window's forecast surplus is neither an executed
    inventory shortfall nor a violation of a fixed-target constraint.
    This check complements, rather than replaces, physical energy replay.
    """
    metadata = problem.metadata or {}
    policy = normalize_bev_terminal_soc_policy(
        metadata.get("bev_terminal_soc_policy"),
        has_explicit_target=metadata.get("final_soc_target_percent") is not None,
    )
    contract = bev_terminal_numeric_acceptance_contract(metadata, gurobi_feasibility_tol=None)
    tolerance = contract["scientific_tolerance_kwh"] + contract["numeric_comparison_margin_kwh"]
    end_slot = max((int(s.slot_index) for s in problem.price_slots), default=-1) + 1
    vehicles = {str(v.vehicle_id): v for v in problem.vehicles}
    used = (set(plan.vehicle_paths()) | set(plan.vehicle_soc_kwh_by_vehicle_slot)
            | {str(c.vehicle_id) for c in plan.charging_slots})
    errors = [f"unknown_vehicle:{vid}" for vid in sorted(used - vehicles.keys())]
    if end_slot <= 0:
        errors.append("empty_execution_horizon")
    daily_mode = metadata.get("bev_soc_deadline_mode") == "next_morning_operational_max"
    timelines = build_vehicle_timeline(problem, plan) if daily_mode else {}
    details = {}
    for vid in sorted(used & vehicles.keys()):
        vehicle = vehicles[vid]
        if not is_electric_vehicle(problem, vehicle):
            continue
        trace = plan.vehicle_soc_kwh_by_vehicle_slot.get(vid, {})
        maximum = vehicle_maximum_soc_kwh(problem, vehicle)
        floor = final_soc_floor_kwh(problem, vehicle)
        target = effective_final_soc_target_kwh(problem, vehicle)
        raw_terminal = trace.get(end_slot)
        terminal = float(raw_terminal) if raw_terminal is not None else None
        failures = []
        if terminal is None or not math.isfinite(terminal):
            failures.append("missing_or_nonfinite_terminal_soc")
            terminal = None
        else:
            if not floor - tolerance <= terminal <= maximum + tolerance:
                failures.append("terminal_soc_outside_operating_bounds")
            if target is not None and terminal < target - tolerance:
                failures.append("terminal_target_shortfall")
            if (policy is BevTerminalSocPolicy.RETURN_TO_INITIAL and target is not None
                    and terminal > target + tolerance):
                failures.append("return_to_initial_surplus")
        deadlines = {}
        if daily_mode:
            for day, slot in fixed_path_soc_target_slots(problem, timelines.get(vid, ())).items():
                raw = trace.get(slot + 1)
                actual = float(raw) if raw is not None else None
                if actual is not None and not math.isfinite(actual):
                    actual = None
                passed = (0 <= slot < end_slot and actual is not None and math.isfinite(actual)
                          and maximum - tolerance <= actual <= maximum + tolerance)
                deadlines[str(day)] = {"boundary_slot": slot + 1, "soc_kwh": actual,
                                       "target_kwh": maximum, "satisfied": passed}
                if not passed:
                    failures.append(f"next_morning_target:{day}")
        initial = vehicle_initial_soc_kwh(problem, vehicle)
        details[vid] = {"policy": policy.value, "initial_soc_kwh": initial,
                        "terminal_boundary_slot": end_slot, "terminal_soc_kwh": terminal,
                        "target_soc_kwh": target, "floor_kwh": floor, "ceiling_kwh": maximum,
                        "inventory_change_kwh": terminal - initial if terminal is not None else None,
                        "daily_deadlines": deadlines, "satisfied": not failures,
                        "failures": failures}
        errors.extend(f"{vid}:{reason}" for reason in failures)
    return {"satisfied": not errors, "basis": "stitched_executed_soc_original_evaluation_policy",
            "numeric_contract": contract, "vehicles": details, "errors": errors}
