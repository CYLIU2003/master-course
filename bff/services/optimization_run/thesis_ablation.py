"""Build same-input day-ahead candidates for the thesis method ablation.

This module never invokes a solver.  It derives M0 and M2 by applying the
audited arrival-immediate charging rule to, respectively, the canonical
baseline assignment and an assignment chosen by a dispatch optimizer. A
charging-only primary result is labeled M1; only an integrated primary result
is labeled M3. Missing methods remain explicit separate-run requirements so
this postprocessor cannot hide additional optimization work inside an ordinary
frontend run.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from typing import Any, Mapping

from src.optimization.baselines import (
    ImmediateChargeBaselineResult,
    build_m0_rule_baseline,
    build_m2_simple_charge_baseline,
)
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.fleet_contract import canonical_powertrain
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
)


SCHEMA_VERSION = "thesis_day_ahead_ablation_candidates_v1"
METHOD_ORDER = ("M0", "M1", "M2", "M3")
CSV_COLUMNS = (
    "method_id",
    "label",
    "construction_status",
    "candidate_available",
    "physical_feasible",
    "day_ahead_comparison_eligible",
    "used_bev_count",
    "used_ice_count",
    "used_other_powertrain_count",
    "bev_trip_count",
    "ice_trip_count",
    "other_powertrain_trip_count",
    "unserved_trip_count",
    "electricity_cost_jpy",
    "fuel_cost_jpy",
    "vehicle_usage_cost_jpy",
    "total_cost_jpy",
    "total_co2_kg",
    "grid_import_kwh",
    "pv_to_bus_kwh",
    "pv_to_bess_kwh",
    "bess_to_bus_kwh",
    "reason",
)


def build_day_ahead_ablation_candidates(
    *,
    problem: CanonicalOptimizationProblem,
    optimized_plan: AssignmentPlan,
    optimized_solver_status: str,
    primary_optimization_structure: str | None = None,
) -> dict[str, Any]:
    """Return structure-aware M0--M3 candidates on one canonical problem."""

    plan_structure = str(
        optimized_plan.metadata.get("optimization_structure") or ""
    ).strip().lower()
    explicit_structure = str(primary_optimization_structure or "").strip().lower()
    if (
        explicit_structure
        and plan_structure
        and explicit_structure != plan_structure
    ):
        raise ValueError(
            "optimization_structure mismatch between engine result and plan: "
            f"{explicit_structure!r} != {plan_structure!r}"
        )
    structure_source = (
        "engine_result.solver_metadata"
        if explicit_structure
        else "plan.metadata"
    )
    primary_structure = str(
        explicit_structure or plan_structure or "unknown"
    ).strip().lower()
    dispatch_plan = optimized_plan
    if primary_structure in {"assignment_only", "two_stage", "integrated"}:
        dispatch_plan = replace(
            optimized_plan,
            metadata={
                **dict(optimized_plan.metadata or {}),
                "optimization_structure": primary_structure,
                "optimization_structure_ablation_provenance": structure_source,
            },
        )
    methods: list[dict[str, Any]] = [
        _build_rule_method(problem, method_id="M0")
    ]
    if primary_structure == "charging_only":
        methods.append(
            _summarize_plan(
                problem,
                optimized_plan,
                method_id="M1",
                label="fixed dispatch plus optimized charging and BESS",
                construction_status="PRIMARY_PHASE1_DAY_AHEAD_RESULT",
                solver_status=optimized_solver_status,
            )
        )
    else:
        methods.append(
            _unavailable_method(
                "M1",
                label="fixed dispatch plus optimized charging and BESS",
                status="SEPARATE_PHASE1_RUN_REQUIRED",
                reason=(
                    "M1 requires an explicit phase1_charging_only run against "
                    "the same prepared input; the frontend postprocessor does "
                    "not silently launch an additional solver."
                ),
            )
        )
    if primary_structure in {"assignment_only", "two_stage", "integrated"}:
        methods.append(
            _build_rule_method(
                problem,
                method_id="M2",
                optimized_plan=dispatch_plan,
            )
        )
    else:
        methods.append(
            _unavailable_method(
                "M2",
                label=_method_label("M2"),
                status="OPTIMIZED_DISPATCH_RUN_REQUIRED",
                reason=(
                    "M2 requires assignment_only, two_stage, or integrated "
                    "dispatch provenance."
                ),
            )
        )
    if primary_structure == "integrated":
        methods.append(
            _summarize_plan(
                problem,
                optimized_plan,
                method_id="M3",
                label="jointly optimized dispatch, charging, PV and BESS",
                construction_status="PRIMARY_PHASE4_DAY_AHEAD_RESULT",
                solver_status=optimized_solver_status,
            )
        )
    else:
        methods.append(
            _unavailable_method(
                "M3",
                label="jointly optimized dispatch, charging, PV and BESS",
                status="SEPARATE_PHASE4_INTEGRATED_RUN_REQUIRED",
                reason=(
                    "M3 is reserved for optimization_structure=integrated; "
                    f"the primary result is {primary_structure!r}."
                ),
            )
        )
    available_ids = [
        str(row["method_id"])
        for row in methods
        if bool(row.get("candidate_available", False))
    ]
    missing_ids = [method_id for method_id in METHOD_ORDER if method_id not in available_ids]
    comparable_ids = [
        str(row["method_id"])
        for row in methods
        if bool(row.get("day_ahead_comparison_eligible", False))
    ]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "COMPLETE_FOUR_METHOD_SET"
            if not missing_ids
            else "PARTIAL_CANDIDATE_SET"
        ),
        "comparison_scope": "same_canonical_problem_day_ahead",
        "primary_optimization_structure": primary_structure,
        "primary_optimization_structure_source": structure_source,
        "cost_basis": "canonical_cost_evaluator_day_ahead",
        "rolling_costs_mixed_into_comparison": False,
        "additional_solver_invoked_by_postprocessor": False,
        "complete_four_method_comparison_available": not missing_ids,
        "available_method_ids": available_ids,
        "day_ahead_comparable_method_ids": comparable_ids,
        "missing_method_ids": missing_ids,
        "research_conclusion_eligible": False,
        "research_claim_limit": (
            "Candidate diagnostics only. Every missing method must be run "
            "explicitly from the same prepared input and frozen SHA before "
            "the four-method ablation supports conclusions."
        ),
        "methods": methods,
    }
    payload["payload_sha256"] = _payload_sha(payload)
    return payload


def ablation_candidate_csv_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten the artifact to stable CSV columns for progress reporting."""

    rows: list[dict[str, Any]] = []
    for method in list(payload.get("methods") or []):
        cost = dict(method.get("cost_breakdown") or {})
        rows.append(
            {
                "method_id": method.get("method_id"),
                "label": method.get("label"),
                "construction_status": method.get("construction_status"),
                "candidate_available": method.get("candidate_available"),
                "physical_feasible": method.get("physical_feasible"),
                "day_ahead_comparison_eligible": method.get(
                    "day_ahead_comparison_eligible"
                ),
                "used_bev_count": method.get("used_bev_count"),
                "used_ice_count": method.get("used_ice_count"),
                "used_other_powertrain_count": method.get(
                    "used_other_powertrain_count"
                ),
                "bev_trip_count": method.get("bev_trip_count"),
                "ice_trip_count": method.get("ice_trip_count"),
                "other_powertrain_trip_count": method.get(
                    "other_powertrain_trip_count"
                ),
                "unserved_trip_count": method.get("unserved_trip_count"),
                "electricity_cost_jpy": cost.get("electricity_cost_final"),
                "fuel_cost_jpy": cost.get("fuel_cost_final"),
                "vehicle_usage_cost_jpy": cost.get("vehicle_usage_cost"),
                "total_cost_jpy": cost.get("total_cost"),
                "total_co2_kg": cost.get("total_co2_kg"),
                "grid_import_kwh": cost.get("grid_import_kwh"),
                "pv_to_bus_kwh": cost.get("pv_to_bus_kwh"),
                "pv_to_bess_kwh": cost.get("pv_to_bess_kwh"),
                "bess_to_bus_kwh": cost.get("bess_to_bus_kwh"),
                "reason": method.get("reason"),
            }
        )
    return rows


def _build_rule_method(
    problem: CanonicalOptimizationProblem,
    *,
    method_id: str,
    optimized_plan: AssignmentPlan | None = None,
) -> dict[str, Any]:
    try:
        if method_id == "M0":
            result = build_m0_rule_baseline(problem)
        else:
            if optimized_plan is None:
                raise ValueError("M2 requires an optimized assignment")
            result = build_m2_simple_charge_baseline(problem, optimized_plan)
    except Exception as exc:
        return {
            "method_id": method_id,
            "label": _method_label(method_id),
            "construction_status": "UNAVAILABLE",
            "candidate_available": False,
            "physical_feasible": False,
            "day_ahead_comparison_eligible": False,
            "research_conclusion_eligible": False,
            "reason": f"{type(exc).__name__}: {exc}",
        }
    return _summarize_rule_result(problem, result, method_id=method_id)


def _unavailable_method(
    method_id: str,
    *,
    label: str,
    status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "method_id": method_id,
        "label": label,
        "construction_status": status,
        "candidate_available": False,
        "physical_feasible": False,
        "day_ahead_comparison_eligible": False,
        "research_conclusion_eligible": False,
        "reason": reason,
    }


def _summarize_rule_result(
    problem: CanonicalOptimizationProblem,
    result: ImmediateChargeBaselineResult,
    *,
    method_id: str,
) -> dict[str, Any]:
    summary = _summarize_plan(
        problem,
        result.plan,
        method_id=method_id,
        label=_method_label(method_id),
        construction_status="RULE_ADAPTER_COMPLETED",
        solver_status="NOT_APPLICABLE_RULE_BASELINE",
    )
    summary["rule_audit"] = dict(result.audit)
    summary["physical_feasible"] = bool(result.feasible)
    summary["physical_errors"] = list(result.errors)
    summary["day_ahead_comparison_eligible"] = bool(
        result.feasible
        and summary.get("unserved_trip_count") == 0
        and summary.get("duplicate_trip_count") == 0
    )
    return summary


def _summarize_plan(
    problem: CanonicalOptimizationProblem,
    plan: AssignmentPlan,
    *,
    method_id: str,
    label: str,
    construction_status: str,
    solver_status: str,
) -> dict[str, Any]:
    validation = FeasibilityChecker().evaluate(problem, plan)
    cost = CostEvaluator().evaluate(problem, plan).to_dict()
    vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    vehicle_type_by_id = {
        str(vehicle_type.vehicle_type_id): vehicle_type
        for vehicle_type in problem.vehicle_types
    }
    used_bev: set[str] = set()
    used_ice: set[str] = set()
    used_other: set[str] = set()
    bev_trip_count = 0
    ice_trip_count = 0
    other_trip_count = 0
    vehicle_paths = plan.vehicle_paths()
    for vehicle_id, trip_ids in vehicle_paths.items():
        vehicle = vehicle_by_id.get(str(vehicle_id))
        vehicle_type = vehicle_type_by_id.get(
            str(getattr(vehicle, "vehicle_type", "") or "")
        )
        powertrain = canonical_powertrain(
            {
                "powertrain": (
                    getattr(vehicle_type, "powertrain_type", None)
                    or getattr(vehicle, "vehicle_type", None)
                ),
                "type": getattr(vehicle, "vehicle_type", None),
            }
        )
        if powertrain in {"BEV", "PHEV", "FCEV"}:
            used_bev.add(str(vehicle_id))
            bev_trip_count += len(trip_ids)
        elif powertrain == "ICE":
            used_ice.add(str(vehicle_id))
            ice_trip_count += len(trip_ids)
        else:
            used_other.add(str(vehicle_id))
            other_trip_count += len(trip_ids)
    metrics = dict(validation.metrics)
    candidate_eligible = bool(
        validation.feasible
        and int(metrics.get("unassigned_trip_count", 0) or 0) == 0
        and int(metrics.get("duplicate_trip_count", 0) or 0) == 0
    )
    return {
        "method_id": method_id,
        "label": label,
        "construction_status": construction_status,
        "solver_status": str(solver_status or ""),
        "candidate_available": True,
        "physical_feasible": bool(validation.feasible),
        "physical_errors": list(validation.errors),
        "physical_validation_metrics": metrics,
        "day_ahead_comparison_eligible": candidate_eligible,
        "research_conclusion_eligible": False,
        "used_bev_count": len(used_bev),
        "used_ice_count": len(used_ice),
        "used_other_powertrain_count": len(used_other),
        "bev_trip_count": bev_trip_count,
        "ice_trip_count": ice_trip_count,
        "other_powertrain_trip_count": other_trip_count,
        "served_trip_count": len(set(plan.served_trip_ids)),
        "unserved_trip_count": int(metrics.get("unassigned_trip_count", 0) or 0),
        "duplicate_trip_count": int(metrics.get("duplicate_trip_count", 0) or 0),
        "assignment": {
            str(vehicle_id): list(trip_ids)
            for vehicle_id, trip_ids in sorted(vehicle_paths.items())
        },
        "cost_breakdown": cost,
        "accounting_source": "CostEvaluator.evaluate(problem, plan)",
    }


def _method_label(method_id: str) -> str:
    return {
        "M0": "rule dispatch plus arrival-immediate charging without BESS",
        "M2": "optimized dispatch plus arrival-immediate charging without BESS",
    }[method_id]


def _payload_sha(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
