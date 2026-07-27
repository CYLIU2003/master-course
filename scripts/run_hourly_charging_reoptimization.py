"""Run fixed-assignment remaining-day charging re-optimization.

This command consumes a persisted Phase 3 day-ahead solver result, keeps its
vehicle-trip assignment unchanged, and re-solves only charging/PV/BESS/grid
dispatch.  The returned schedule is a receding-horizon control proposal: only
the first ``execution_minutes`` should be executed before measured state is
updated and the command is called again.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.routers.optimization import (  # noqa: E402
    _prepare_weather_policy_for_scenario,
    _prepared_inputs_root,
)
from bff.services.run_preparation import (  # noqa: E402
    load_prepared_input,
    materialize_scenario_from_prepared_input,
)
from bff.store import scenario_store as store  # noqa: E402
from src.dispatch.models import hhmm_to_min  # noqa: E402
from src.gurobi_runtime import is_gurobi_available  # noqa: E402
from src.optimization import (  # noqa: E402
    OptimizationConfig,
    OptimizationMode,
    ProblemBuilder,
    ResultSerializer,
)
from src.optimization.common.research_phase3_policy import (  # noqa: E402
    enforce_research_phase3_single_continuous_duty,
)
from src.optimization.common.evaluator import CostEvaluator  # noqa: E402
from src.optimization.common.problem import (  # noqa: E402
    AssignmentPlan,
    classify_peak_slots,
)
from src.optimization.common.bev_terminal_policy import (  # noqa: E402
    normalize_bev_terminal_soc_policy,
)
from src.optimization.common.bess_terminal_policy import (  # noqa: E402
    normalize_bess_terminal_policy,
    resolve_bess_terminal_soc_target_kwh,
)
from src.optimization.common.input_fingerprints import (  # noqa: E402
    INPUT_FINGERPRINT_SCHEMA,
)
from src.optimization.common.initial_soc_policy import (  # noqa: E402
    initial_soc_input_metadata,
    normalize_initial_soc_policy,
)
from src.optimization.rolling.reoptimizer import (  # noqa: E402
    RollingReoptimizer,
    assignment_plan_from_serialized_result,
)
from src.optimization.rolling.day_ahead_hourly import (  # noqa: E402
    build_next_execution_state,
)
from src.preprocess.weather.operation_policy import (  # noqa: E402
    apply_weather_policy_to_problem,
)
from scripts.run_research_phase3_frontend_weather import (  # noqa: E402
    _git_state,
    _trip_input_hash,
    _vehicle_input_hash,
)
from scripts.compare_research_phase3_weather import _validate_manifest  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _minute_label(minute: int) -> str:
    minute_of_day = int(minute) % (24 * 60)
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git_snapshot(repo_root: Path) -> tuple[str, bool]:
    """Return the exact rolling-runner commit and whether it has local edits."""

    if repo_root.resolve() != REPO_ROOT.resolve():
        raise ValueError("Git snapshot must be taken from the repository root")
    state = _git_state()
    sha = str(state.get("git_sha") or "")
    dirty = state.get("git_dirty")
    # Missing provenance is never equivalent to a clean research run.
    return sha, dirty is not False


_EXECUTED_SLOT_MAP_FIELDS = (
    "grid_to_bus_kwh_by_depot_slot",
    "pv_to_bus_kwh_by_depot_slot",
    "bess_to_bus_kwh_by_depot_slot",
    "pv_to_bess_kwh_by_depot_slot",
    "grid_to_bess_kwh_by_depot_slot",
    "pv_curtail_kwh_by_depot_slot",
    "bess_soc_kwh_by_depot_slot",
    "contract_over_limit_kwh_by_depot_slot",
)


def _merge_executed_slot_values(
    target: dict[str, dict[int, float]],
    source: Any,
    *,
    start_slot: int,
    stop_slot: int,
    field_name: str,
    tolerance: float = 1.0e-9,
) -> None:
    """Copy one executed window and reject contradictory duplicate values."""

    for raw_owner_id, raw_slot_map in dict(source or {}).items():
        owner_id = str(raw_owner_id)
        owner_values = target.setdefault(owner_id, {})
        for raw_slot, raw_value in dict(raw_slot_map or {}).items():
            slot = int(raw_slot)
            if slot < start_slot or slot >= stop_slot:
                continue
            value = float(raw_value or 0.0)
            if not math.isfinite(value):
                raise ValueError(
                    f"{field_name}[{owner_id!r}][{slot}] must be finite"
                )
            existing = owner_values.get(slot)
            if existing is not None and abs(existing - value) > tolerance:
                raise ValueError(
                    "Executed rolling windows disagree for "
                    f"{field_name}[{owner_id!r}][{slot}]: "
                    f"existing={existing}, new={value}"
                )
            owner_values[slot] = value


def _build_executed_day_accounting(
    problem: Any,
    day_ahead_plan: AssignmentPlan,
    executed_segments: list[tuple[Any, Any, int, int]],
) -> dict[str, Any]:
    """Recalculate one day from executed prefixes, never from look-ahead totals.

    Each segment is ``(step_problem, result, start_slot, stop_slot)``. Energy
    slots use ``[start_slot, stop_slot)``. Vehicle SOC uses boundary values and
    therefore also retains ``stop_slot``. Duplicate coverage is rejected rather
    than silently double-counted.
    """

    expected_slots = {int(slot.slot_index) for slot in problem.price_slots}
    coverage_count = {slot: 0 for slot in expected_slots}
    stitched_maps: dict[str, dict[str, dict[int, float]]] = {
        field_name: {} for field_name in _EXECUTED_SLOT_MAP_FIELDS
    }
    vehicle_soc: dict[str, dict[int, float]] = {}
    charging_slots = []
    seen_charging_slots: set[tuple[str, int, str, str]] = set()
    executed_pv_profiles = {
        str(depot_id): list(asset.pv_generation_kwh_by_slot or ())
        for depot_id, asset in dict(problem.depot_energy_assets or {}).items()
    }

    for step_problem, result, start_slot, stop_slot in executed_segments:
        for slot in range(start_slot, stop_slot):
            if slot in coverage_count:
                coverage_count[slot] += 1
        plan = result.plan
        for field_name in _EXECUTED_SLOT_MAP_FIELDS:
            _merge_executed_slot_values(
                stitched_maps[field_name],
                getattr(plan, field_name),
                start_slot=start_slot,
                stop_slot=stop_slot,
                field_name=field_name,
            )
        _merge_executed_slot_values(
            vehicle_soc,
            plan.vehicle_soc_kwh_by_vehicle_slot,
            start_slot=start_slot,
            stop_slot=stop_slot + 1,
            field_name="vehicle_soc_kwh_by_vehicle_slot",
        )
        for charging_slot in plan.charging_slots:
            slot = int(charging_slot.slot_index)
            if slot < start_slot or slot >= stop_slot:
                continue
            key = (
                str(charging_slot.vehicle_id),
                slot,
                str(charging_slot.charger_id or ""),
                str(charging_slot.energy_source or ""),
            )
            if key not in seen_charging_slots:
                charging_slots.append(charging_slot)
                seen_charging_slots.add(key)

        for depot_id, step_asset in dict(
            step_problem.depot_energy_assets or {}
        ).items():
            profile = list(step_asset.pv_generation_kwh_by_slot or ())
            target_profile = executed_pv_profiles.setdefault(str(depot_id), profile[:])
            if len(target_profile) < len(profile):
                target_profile.extend(profile[len(target_profile) :])
            for slot in range(start_slot, min(stop_slot, len(profile))):
                target_profile[slot] = float(profile[slot])

    missing_slots = sorted(slot for slot, count in coverage_count.items() if count == 0)
    duplicate_slots = sorted(slot for slot, count in coverage_count.items() if count > 1)
    complete_coverage = bool(expected_slots) and not missing_slots and not duplicate_slots
    if not complete_coverage:
        return {
            "eligible": False,
            "reason": "executed_slot_coverage_incomplete",
            "expected_slot_count": len(expected_slots),
            "executed_slot_count": sum(count > 0 for count in coverage_count.values()),
            "missing_slots": missing_slots,
            "duplicate_slots": duplicate_slots,
            "cost_breakdown": None,
        }

    stitched_assets = {
        str(depot_id): replace(
            asset,
            pv_generation_kwh_by_slot=tuple(
                executed_pv_profiles.get(str(depot_id), ())
            ),
        )
        for depot_id, asset in dict(problem.depot_energy_assets or {}).items()
    }
    accounting_problem = replace(problem, depot_energy_assets=stitched_assets)
    accounting_plan = replace(
        day_ahead_plan,
        charging_slots=tuple(charging_slots),
        vehicle_soc_kwh_by_vehicle_slot=vehicle_soc,
        metadata={
            **dict(day_ahead_plan.metadata or {}),
            "rolling_execution_accounting": True,
            "rolling_executed_slot_count": len(expected_slots),
        },
        **stitched_maps,
    )
    breakdown = CostEvaluator().evaluate(accounting_problem, accounting_plan).to_dict()
    bev_terminal_balanced = all(
        bool(
            {
                **dict(getattr(segment_result.plan, "metadata", {}) or {}),
                **dict(getattr(segment_result, "solver_metadata", {}) or {}),
            }.get("bev_terminal_soc_balance_satisfied")
        )
        for _, segment_result, _, _ in executed_segments
    )
    bess_terminal_details: dict[str, dict[str, Any]] = {}
    bess_terminal_balanced = True
    for depot_id, asset in dict(problem.depot_energy_assets or {}).items():
        if not bool(getattr(asset, "bess_enabled", False)):
            continue
        policy = normalize_bess_terminal_policy(
            getattr(asset, "bess_terminal_soc_policy", ""),
            has_explicit_target=(
                float(getattr(asset, "bess_terminal_soc_target_kwh", 0.0) or 0.0)
                > 0.0
            ),
        )
        target_kwh = resolve_bess_terminal_soc_target_kwh(
            policy=policy,
            initial_soc_kwh=float(asset.bess_initial_soc_kwh or 0.0),
            configured_target_kwh=float(
                asset.bess_terminal_soc_target_kwh or 0.0
            ),
            terminal_soc_floor_kwh=max(
                float(asset.bess_terminal_soc_min_kwh or 0.0),
                float(asset.bess_soc_min_kwh or 0.0),
            ),
            maximum_soc_kwh=float(asset.bess_soc_max_kwh or 0.0),
        )
        trajectory = dict(
            stitched_maps["bess_soc_kwh_by_depot_slot"].get(str(depot_id)) or {}
        )
        terminal_kwh = (
            float(trajectory[max(trajectory)]) if trajectory else None
        )
        deviation_kwh = (
            abs(terminal_kwh - target_kwh)
            if terminal_kwh is not None and target_kwh is not None
            else None
        )
        depot_balanced = deviation_kwh is not None and deviation_kwh <= 1.0e-6
        bess_terminal_balanced = bess_terminal_balanced and depot_balanced
        bess_terminal_details[str(depot_id)] = {
            "policy": policy,
            "initial_soc_kwh": float(asset.bess_initial_soc_kwh or 0.0),
            "target_soc_kwh": target_kwh,
            "terminal_soc_kwh": terminal_kwh,
            "absolute_deviation_kwh": deviation_kwh,
            "balanced": depot_balanced,
        }
    unreplenished_kwh = float(
        breakdown.get("ev_unreplenished_drive_energy_kwh", 0.0) or 0.0
    )
    rejection_reasons = []
    if not bev_terminal_balanced:
        rejection_reasons.append("bev_terminal_energy_not_balanced")
    if not bess_terminal_balanced:
        rejection_reasons.append("bess_terminal_energy_not_balanced")
    if unreplenished_kwh > 1.0e-6:
        rejection_reasons.append("unreplenished_drive_energy_remains")
    eligible = not rejection_reasons
    return {
        "eligible": eligible,
        "reason": None if eligible else "terminal_energy_inventory_not_balanced",
        "rejection_reasons": rejection_reasons,
        "accounting_basis": (
            "executed_hourly_energy_flows_plus_inventory_valuation_for_unrefueled_fuel"
        ),
        "objective_aggregation": "executed_prefixes_stitched_then_recalculated_once",
        "expected_slot_count": len(expected_slots),
        "executed_slot_count": len(expected_slots),
        "missing_slots": [],
        "duplicate_slots": [],
        "terminal_energy_balanced": (
            bev_terminal_balanced and bess_terminal_balanced
        ),
        "bev_terminal_energy_balanced": bev_terminal_balanced,
        "bess_terminal_energy_balanced": bess_terminal_balanced,
        "bess_terminal_soc_by_depot": bess_terminal_details,
        "cost_breakdown": breakdown,
        "executed_energy_flow_hash": _canonical_hash(
            {field_name: stitched_maps[field_name] for field_name in _EXECUTED_SLOT_MAP_FIELDS}
        ),
    }


def _apply_pv_forecast_update(
    problem: Any,
    raw_update: Any,
) -> tuple[Any, dict[str, Any]]:
    """Apply an explicit full-horizon PV forecast without changing history."""

    if not isinstance(raw_update, dict):
        raise ValueError("Each PV forecast update must be a JSON object")
    raw_profiles = raw_update.get("forecast_by_depot", raw_update)
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError("PV forecast update requires forecast_by_depot")
    assets = dict(problem.depot_energy_assets or {})
    unknown_depots = sorted(set(map(str, raw_profiles)).difference(assets))
    if unknown_depots:
        raise ValueError(
            f"PV forecast update references unknown depots: {unknown_depots}"
        )
    required_slot_count = max(
        (int(slot.slot_index) for slot in problem.price_slots),
        default=-1,
    ) + 1
    normalized_profiles: dict[str, list[float]] = {}
    for raw_depot_id, raw_values in raw_profiles.items():
        depot_id = str(raw_depot_id)
        if not isinstance(raw_values, list):
            raise ValueError(
                f"PV forecast for depot {depot_id!r} must be a list"
            )
        values = [float(value) for value in raw_values]
        if len(values) < required_slot_count:
            raise ValueError(
                f"PV forecast for depot {depot_id!r} has {len(values)} slots; "
                f"at least {required_slot_count} are required"
            )
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError(
                "PV forecast values must be finite, non-negative kWh"
            )
        normalized_profiles[depot_id] = values
        assets[depot_id] = replace(
            assets[depot_id],
            pv_generation_kwh_by_slot=tuple(values),
        )
    serialized = json.dumps(
        normalized_profiles,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    audit = {
        "depot_ids": sorted(normalized_profiles),
        "pv_generation_kwh_by_depot": {
            depot_id: sum(values)
            for depot_id, values in sorted(normalized_profiles.items())
        },
        "profile_hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "semantics": "full_horizon_forecast_replaced_before_current_hour_solve",
    }
    return replace(problem, depot_energy_assets=assets), audit


def _depot_energy_assets_fixed_hash(problem: Any) -> str:
    """Hash non-PV-curve depot controls using the day-ahead snapshot schema.

    The snapshot originates in the day-ahead research runner, which is the
    single source of truth for this artifact schema. Keeping the same helper
    prevents a rolling run from treating BESS configuration changes as a
    harmless PV forecast update.
    """

    # The day-ahead runner imports the rolling service only for an explicit
    # rolling request, so this local import avoids a module-import cycle.
    from scripts.run_research_phase3_frontend_weather import _asset_snapshot

    snapshot = _asset_snapshot(problem)
    fixed_snapshot = {
        depot_id: {
            key: value
            for key, value in dict(asset).items()
            if key not in {"pv_generation_kwh", "pv_generation_hash"}
        }
        for depot_id, asset in sorted(snapshot.items())
    }
    return _canonical_hash(fixed_snapshot)


def _load_day_ahead_effective_pv_profiles(
    *,
    day_ahead_output_dir: Path,
    input_audit: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Load and hash-verify the resolved PV curve used by day-ahead planning."""

    artifact_name = str(
        input_audit.get("effective_pv_profiles_artifact") or ""
    ).strip()
    expected_sha256 = str(
        input_audit.get("effective_pv_profiles_sha256") or ""
    ).strip()
    if not artifact_name or not expected_sha256:
        raise ValueError(
            "Day-ahead input audit is missing effective PV profile provenance"
        )
    profile_path = day_ahead_output_dir / artifact_name
    if not profile_path.is_file():
        raise ValueError(
            "Day-ahead effective PV profile artifact is missing: "
            f"{profile_path}"
        )
    actual_sha256 = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "Day-ahead effective PV profile artifact hash does not match "
            "input_audit.json"
        )
    payload = _load_json(profile_path)
    if str(payload.get("schema_version") or "") != "effective_pv_profiles_v1":
        raise ValueError("Unsupported effective PV profile artifact schema")
    return payload, actual_sha256


def _validate_day_ahead_input_contract(
    problem: Any,
    input_audit: dict[str, Any],
    *,
    scenario_id: str,
    prepared_input_id: str,
    service_date: str,
    service_id: str,
) -> None:
    """Ensure the persisted assignment was solved from the current inputs."""

    initial_soc_policy = normalize_initial_soc_policy(
        str(input_audit.get("initial_soc_policy") or "")
    )
    current_initial_soc = initial_soc_input_metadata(
        problem,
        policy=initial_soc_policy,
    )
    current_charger_hash = _charger_configuration_hash(problem)
    current_pv_hashes = {
        str(depot_id): _canonical_hash(
            list(asset.pv_generation_kwh_by_slot or ())
        )
        for depot_id, asset in dict(problem.depot_energy_assets or {}).items()
    }
    expected_pv_hashes = {
        str(depot_id): str(
            dict(asset or {}).get("pv_generation_hash") or ""
        )
        for depot_id, asset in dict(input_audit.get("depot_energy_assets") or {}).items()
    }
    current_fixed_asset_hash = _depot_energy_assets_fixed_hash(problem)
    expected_values = {
        "input_fingerprint_schema": INPUT_FINGERPRINT_SCHEMA,
        "scenario_id": str(scenario_id),
        "prepared_input_id": str(prepared_input_id),
        "service_date": str(service_date),
        "trip_input_hash": _trip_input_hash(problem),
        "vehicle_input_hash": _vehicle_input_hash(problem),
        "bev_terminal_soc_policy": str(
            problem.metadata.get("bev_terminal_soc_policy") or ""
        ),
        "service_id": str(service_id),
        "timestep_min": str(int(problem.scenario.timestep_min)),
        "price_slot_count": str(len(problem.price_slots)),
        "charger_configuration_hash": current_charger_hash,
        "initial_soc_input_hash": str(current_initial_soc["initial_soc_input_hash"]),
        "depot_energy_assets_fixed_hash": current_fixed_asset_hash,
    }
    audited_terminal_policy = str(
        input_audit.get("bev_terminal_soc_policy")
        or dict(input_audit.get("terminal_soc_policy") or {}).get(
            "bev_terminal_soc_policy"
        )
        or ""
    )
    input_audit = {
        **input_audit,
        "bev_terminal_soc_policy": audited_terminal_policy,
    }
    mismatches = {
        key: {"expected": expected, "actual": str(input_audit.get(key) or "")}
        for key, expected in expected_values.items()
        if str(input_audit.get(key) or "") != expected
    }
    if mismatches:
        raise ValueError(
            "Persisted day-ahead input contract does not match the current problem: "
            f"{mismatches}"
        )
    if expected_pv_hashes and current_pv_hashes != expected_pv_hashes:
        raise ValueError(
            "Persisted day-ahead PV profiles do not match the current rolling "
            f"problem: expected={expected_pv_hashes}, actual={current_pv_hashes}"
        )


def _gurobi_version_snapshot() -> dict[str, Any]:
    """Record the solver backend name and version without hiding failures."""

    backend = "gurobi"
    version: str | None = None
    if not is_gurobi_available():
        return {
            "backend": backend,
            "version": None,
            "available": False,
            "capture_error": "gurobi_runtime_unavailable",
        }
    try:
        from src.gurobi_runtime import gp as _gp  # local import keeps module import cheap

        if _gp is not None and hasattr(_gp, "gurobi"):
            raw = _gp.gurobi.version()
            if isinstance(raw, (list, tuple)):
                version = ".".join(str(item) for item in raw)
            else:
                version = str(raw)
    except Exception as exc:  # pragma: no cover - environment-only failure
        return {
            "backend": backend,
            "version": None,
            "available": False,
            "capture_error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "backend": backend,
        "version": version,
        "available": True,
        "capture_error": None,
    }


def _day_ahead_assignment_hash(plan: AssignmentPlan) -> str:
    """Hash the vehicle-trip assignment so chain steps can prove it is fixed."""

    duties = []
    for duty in sorted(plan.duties, key=lambda item: str(item.duty_id)):
        duties.append(
            {
                "duty_id": str(duty.duty_id),
                "vehicle_type": str(duty.vehicle_type or ""),
                "trip_ids": [str(trip_id) for trip_id in duty.trip_ids],
                "deadhead_from_prev_min": [
                    int(leg.deadhead_from_prev_min or 0) for leg in duty.legs
                ],
            }
        )
    served = [str(trip_id) for trip_id in plan.served_trip_ids]
    unserved = [str(trip_id) for trip_id in plan.unserved_trip_ids]
    duty_vehicle_map = plan.duty_vehicle_map()
    return _canonical_hash(
        {
            "duties": duties,
            "served_trip_ids": served,
            "unserved_trip_ids": unserved,
            "duty_vehicle_map": {
                str(key): str(value) for key, value in sorted(duty_vehicle_map.items())
            },
        }
    )


def _pv_forecast_hash(problem: Any) -> str:
    """Pin the full-horizon PV curves used by day-ahead and rolling solves."""

    payload = {
        str(depot_id): [float(value or 0.0) for value in (asset.pv_generation_kwh_by_slot or ())]
        for depot_id, asset in sorted((problem.depot_energy_assets or {}).items())
    }
    return _canonical_hash(payload)


def _charger_configuration_hash(problem: Any) -> str:
    payload = [
        {
            "charger_id": str(charger.charger_id),
            "depot_id": str(charger.depot_id),
            "power_kw": float(charger.power_kw),
            "bidirectional": bool(charger.bidirectional),
            "simultaneous_ports": int(charger.simultaneous_ports),
        }
        for charger in sorted(problem.chargers, key=lambda item: str(item.charger_id))
    ]
    return _canonical_hash(payload)


def _assert_duties_unchanged(day_ahead_hash: str, result: Any) -> dict[str, Any]:
    """Record whether a rolling step preserved the fixed vehicle-trip assignment."""

    plan = result.plan if hasattr(result, "plan") else None
    if plan is None:
        return {
            "fixed_assignment_check": "missing_plan",
            "day_ahead_assignment_hash": day_ahead_hash,
            "step_assignment_hash": None,
            "matched": False,
        }
    step_hash = _day_ahead_assignment_hash(plan)
    return {
        "fixed_assignment_check": (
            "matched" if step_hash == day_ahead_hash else "changed"
        ),
        "day_ahead_assignment_hash": day_ahead_hash,
        "step_assignment_hash": step_hash,
        "matched": bool(step_hash == day_ahead_hash),
    }


def _finite(value: Any) -> float | None:
    """Return a finite float, otherwise None.

    Mirrors ``scripts.run_research_phase3_frontend_weather._finite`` so the
    rolling runner can compare cost/energy values without importing the
    heavier day-ahead runner module.
    """

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _build_day_ahead_vs_rolling_summary(
    *,
    day_ahead_summary: dict[str, Any],
    executed_day_accounting: dict[str, Any],
    day_ahead_assignment_hash: str,
    step_assignment_hashes: list[bool],
    step_count: int,
) -> dict[str, Any]:
    """Compare the day-ahead plan and the executed rolling chain inline.

    Only fields that exist in both summaries are compared on the same unit.
    Missing fields or units are reported as ``null`` with an explicit reason
    so a chart cannot imply a comparison the data does not support.
    """

    breakdown = dict(executed_day_accounting.get("cost_breakdown") or {})
    comparisons: dict[str, Any] = {}
    cost_keys = (
        "total_cost",
        "accounting_total_cost_jpy",
        "electricity_cost",
        "fuel_cost",
        "co2_cost",
        "demand_cost",
        "vehicle_cost",
        "vehicle_usage_cost",
    )
    for key in cost_keys:
        day_ahead_value = _finite(day_ahead_summary.get(key))
        rolling_value = _finite(breakdown.get(key))
        if day_ahead_value is None or rolling_value is None:
            comparisons[key] = {
                "day_ahead": day_ahead_value,
                "rolling_executed": rolling_value,
                "difference": None,
                "comparable": False,
                "reason": (
                    "missing_in_day_ahead"
                    if day_ahead_value is None
                    else "missing_in_rolling_accounting"
                ),
            }
        else:
            comparisons[key] = {
                "day_ahead": day_ahead_value,
                "rolling_executed": rolling_value,
                "difference": rolling_value - day_ahead_value,
                "comparable": True,
                "reason": "same_unit_jpy",
                "note": (
                    "Day-ahead is the planning plan evaluation; rolling is the "
                    "executed-chain accounting evaluation."
                ),
            }
    energy_keys = (
        "grid_import_kwh",
        "grid_to_bus_kwh",
        "grid_to_bess_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "bess_to_bus_kwh",
        "pv_curtailed_kwh",
        "peak_grid_kw",
    )
    for key in energy_keys:
        day_ahead_value = _finite(day_ahead_summary.get(key))
        rolling_value = _finite(breakdown.get(key))
        if day_ahead_value is None or rolling_value is None:
            comparisons[key] = {
                "day_ahead": day_ahead_value,
                "rolling_executed": rolling_value,
                "difference": None,
                "comparable": False,
                "reason": (
                    "missing_in_day_ahead"
                    if day_ahead_value is None
                    else "missing_in_rolling_accounting"
                ),
            }
        else:
            comparisons[key] = {
                "day_ahead": day_ahead_value,
                "rolling_executed": rolling_value,
                "difference": rolling_value - day_ahead_value,
                "comparable": True,
                "reason": "same_unit_kwh_or_kw",
                "note": (
                    "Both values are evaluated on the same depot/slot energy "
                    "ledger definition."
                ),
            }
    return {
        "schema_version": "day_ahead_vs_rolling_summary_v1",
        "step_count_executed": step_count,
        "day_ahead_assignment_hash": day_ahead_assignment_hash,
        "rolling_assignment_hash_constant": bool(step_assignment_hashes) and all(
            step_assignment_hashes
        ),
        "compare_scope": (
            "Day-ahead planning evaluation vs. executed rolling chain "
            "accounting evaluation. Both are cost/energy values in the same "
            "units; neither is the integrated global optimum."
        ),
        "fields": comparisons,
    }


def _write_hourly_chart_csv(
    path: Path,
    *,
    problem: Any,
    executed_segments: list[tuple[Any, Any, int, int]],
) -> None:
    """Write a per-hour energy flow table for the supervisor figures.

    One row per step records only the executed window's PV/grid/BESS flow and
    charger power.  Remaining-horizon objective values are intentionally not
    written here because adding or charting them as realised daily cost would
    double-count future slots.
    """

    import csv as _csv

    field_names = [
        "step_index",
        "current_time",
        "execution_minutes",
        "pv_generated_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "pv_curtailed_kwh",
        "bess_to_bus_kwh",
        "grid_to_bus_kwh",
        "grid_to_bess_kwh",
        "bess_end_soc_kwh_by_depot",
        "bev_soc_min_kwh",
        "bev_soc_mean_kwh",
        "charging_kw_max",
        "on_peak_kw_max",
        "off_peak_kw_max",
        "vehicle_source_provenance_exact",
        "vehicle_source_allocation_policy",
    ]
    rows: list[dict[str, Any]] = []
    timestep_h = max(int(problem.scenario.timestep_min), 1) / 60.0
    observed_on_peak_by_depot: dict[str, float] = {}
    observed_off_peak_by_depot: dict[str, float] = {}
    for step_index, (step_problem, result, start_slot, stop_slot) in enumerate(
        executed_segments
    ):
        plan = result.plan
        metadata = {
            **dict(getattr(plan, "metadata", {}) or {}),
            **dict(getattr(result, "solver_metadata", {}) or {}),
        }

        def _sum_slots(field_name: str) -> float:
            source = dict(getattr(plan, field_name, {}) or {})
            return float(
                sum(
                    float(value or 0.0)
                    for slot_map in source.values()
                    for slot, value in dict(slot_map or {}).items()
                    if start_slot <= int(slot) < stop_slot
                )
            )

        pv_generated = float(
            sum(
                float(value or 0.0)
                for asset in dict(step_problem.depot_energy_assets or {}).values()
                for value in list(asset.pv_generation_kwh_by_slot or ())[start_slot:stop_slot]
            )
        )
        charging_kw_max = max(
            (
                sum(
                    max(float(slot.charge_kw or 0.0), 0.0)
                    for slot in plan.charging_slots
                    if int(slot.slot_index) == slot_index
                )
                for slot_index in range(start_slot, stop_slot)
            ),
            default=0.0,
        )
        bess_end = {
            str(depot_id): float(slot_map[stop_slot - 1])
            for depot_id, slot_map in dict(
                plan.bess_soc_kwh_by_depot_slot or {}
            ).items()
            if stop_slot - 1 in dict(slot_map or {})
        }
        vehicle_soc_values = [
            float(value)
            for slot_map in dict(plan.vehicle_soc_kwh_by_vehicle_slot or {}).values()
            for slot, value in dict(slot_map or {}).items()
            if start_slot <= int(slot) <= stop_slot
        ]
        on_peak_slots, off_peak_slots = classify_peak_slots(step_problem.price_slots)
        grid_bus = dict(plan.grid_to_bus_kwh_by_depot_slot or {})
        grid_bess = dict(plan.grid_to_bess_kwh_by_depot_slot or {})
        for depot_id in dict(step_problem.depot_energy_assets or {}):
            depot_key = str(depot_id)
            bus_by_slot = dict(grid_bus.get(depot_key) or {})
            bess_by_slot = dict(grid_bess.get(depot_key) or {})
            for slot_index in range(start_slot, stop_slot):
                import_kw = (
                    float(bus_by_slot.get(slot_index, 0.0) or 0.0)
                    + float(bess_by_slot.get(slot_index, 0.0) or 0.0)
                ) / timestep_h
                if slot_index in on_peak_slots:
                    observed_on_peak_by_depot[depot_key] = max(
                        observed_on_peak_by_depot.get(depot_key, 0.0), import_kw
                    )
                elif slot_index in off_peak_slots:
                    observed_off_peak_by_depot[depot_key] = max(
                        observed_off_peak_by_depot.get(depot_key, 0.0), import_kw
                    )
        rows.append(
            {
                "step_index": step_index,
                "current_time": _minute_label(
                    hhmm_to_min(str(step_problem.scenario.horizon_start))
                    + start_slot * int(step_problem.scenario.timestep_min)
                ),
                "execution_minutes": int((stop_slot - start_slot) * timestep_h * 60),
                "pv_generated_kwh": pv_generated,
                "pv_to_bus_kwh": _sum_slots("pv_to_bus_kwh_by_depot_slot"),
                "pv_to_bess_kwh": _sum_slots("pv_to_bess_kwh_by_depot_slot"),
                "pv_curtailed_kwh": _sum_slots("pv_curtail_kwh_by_depot_slot"),
                "bess_to_bus_kwh": _sum_slots("bess_to_bus_kwh_by_depot_slot"),
                "grid_to_bus_kwh": _sum_slots("grid_to_bus_kwh_by_depot_slot"),
                "grid_to_bess_kwh": _sum_slots("grid_to_bess_kwh_by_depot_slot"),
                "bess_end_soc_kwh_by_depot": json.dumps(
                    bess_end, ensure_ascii=False, sort_keys=True
                ),
                "bev_soc_min_kwh": min(vehicle_soc_values, default=None),
                "bev_soc_mean_kwh": (
                    sum(vehicle_soc_values) / len(vehicle_soc_values)
                    if vehicle_soc_values
                    else None
                ),
                "charging_kw_max": charging_kw_max,
                "on_peak_kw_max": max(
                    observed_on_peak_by_depot.values(), default=0.0
                ),
                "off_peak_kw_max": max(
                    observed_off_peak_by_depot.values(), default=0.0
                ),
                "vehicle_source_provenance_exact": metadata.get(
                    "vehicle_source_provenance_exact"
                ),
                "vehicle_source_allocation_policy": metadata.get(
                    "vehicle_source_allocation_policy"
                ),
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = _csv.DictWriter(handle, fieldnames=field_names)
        writer.writeheader()
        writer.writerows(rows)


def _write_executed_charging_schedule(
    path: Path,
    *,
    problem: Any,
    executed_segments: list[tuple[Any, Any, int, int]],
) -> None:
    """Write the physically executed charging prefixes with source semantics."""

    import csv as _csv

    timestep_h = max(int(problem.scenario.timestep_min), 1) / 60.0
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    for step_problem, result, start_slot, stop_slot in executed_segments:
        metadata = {
            **dict(getattr(result.plan, "metadata", {}) or {}),
            **dict(getattr(result, "solver_metadata", {}) or {}),
        }
        for slot in result.plan.charging_slots:
            slot_index = int(slot.slot_index)
            if not start_slot <= slot_index < stop_slot:
                continue
            key = (
                str(slot.vehicle_id),
                slot_index,
                str(slot.charger_id or ""),
                str(slot.energy_source or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "vehicle_id": str(slot.vehicle_id),
                    "slot_index": slot_index,
                    "time": _minute_label(
                        hhmm_to_min(str(step_problem.scenario.horizon_start))
                        + slot_index * int(step_problem.scenario.timestep_min)
                    ),
                    "charger_id": str(slot.charger_id or ""),
                    "charging_depot_id": str(slot.charging_depot_id or ""),
                    "energy_source": str(slot.energy_source or "unspecified"),
                    "charge_kw": float(slot.charge_kw or 0.0),
                    "energy_kwh": float(slot.charge_kw or 0.0) * timestep_h,
                    "vehicle_source_provenance_exact": metadata.get(
                        "vehicle_source_provenance_exact"
                    ),
                    "vehicle_source_allocation_policy": metadata.get(
                        "vehicle_source_allocation_policy"
                    ),
                }
            )
    rows.sort(
        key=lambda row: (
            row["slot_index"],
            row["vehicle_id"],
            row["charger_id"],
            row["energy_source"],
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = _csv.DictWriter(
            handle,
            fieldnames=[
                "vehicle_id",
                "slot_index",
                "time",
                "charger_id",
                "charging_depot_id",
                "energy_source",
                "charge_kw",
                "energy_kwh",
                "vehicle_source_provenance_exact",
                "vehicle_source_allocation_policy",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    request = RollingChainRequest.from_args(args)
    return run_rolling_chain(request, args=args)


@dataclass(frozen=True)
class RollingChainRequest:
    """Explicit, testable inputs for the full hourly rolling chain.

    The CLI ``run`` wrapper builds this and calls :func:`run_rolling_chain`.
    Tests may construct it directly without going through ``argparse``. Every
    required rolling configuration is captured here so the run manifest and
    chain summary can record it without implicit defaults.
    """

    scenario_id: str
    prepared_input_id: str
    expected_service_date: str
    day_ahead_result_path: str
    output_dir: str
    current_time: Optional[str] = None
    end_time: Optional[str] = None
    full_chain: bool = False
    execution_minutes: int = 60
    time_limit_sec: int = 30
    mip_gap: float = 0.1
    random_seed: int = 42
    gurobi_threads: Optional[int] = None
    depot_id: str = "tsurumaki"
    service_id: str = "WEEKDAY"
    state_json: Optional[str] = None
    pv_forecast_updates_json: Optional[str] = None
    bess_terminal_policy: str = "scenario"
    bess_terminal_min_kwh: Optional[float] = None
    # Production BFF calls pass the exact canonical problem that produced the
    # sibling day-ahead result. CLI calls leave this unset and reconstruct from
    # the persisted, hash-pinned effective scenario.
    day_ahead_problem: Optional[Any] = None

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "RollingChainRequest":
        return cls(
            scenario_id=str(args.scenario_id),
            prepared_input_id=str(args.prepared_input_id),
            expected_service_date=str(args.expected_service_date),
            day_ahead_result_path=str(args.day_ahead_result),
            output_dir=str(args.output_dir),
            current_time=getattr(args, "current_time", None),
            end_time=getattr(args, "end_time", None),
            full_chain=bool(getattr(args, "full_chain", False)),
            execution_minutes=int(args.execution_minutes),
            time_limit_sec=int(args.time_limit_sec),
            mip_gap=float(args.mip_gap),
            random_seed=int(args.random_seed),
            gurobi_threads=getattr(args, "gurobi_threads", None),
            depot_id=str(args.depot_id),
            service_id=str(args.service_id),
            state_json=getattr(args, "state_json", None),
            pv_forecast_updates_json=getattr(args, "pv_forecast_updates_json", None),
            bess_terminal_policy=str(args.bess_terminal_policy),
            bess_terminal_min_kwh=(
                None if args.bess_terminal_min_kwh is None else float(args.bess_terminal_min_kwh)
            ),
        )


def run_rolling_chain(
    request: RollingChainRequest,
    *,
    args: Optional[argparse.Namespace] = None,
) -> int:
    """Execute a fixed-assignment remaining-day charging re-optimization chain.

    This is the testable service behind ``run``. It deliberately mirrors the
    historical command sequence so the persisted artifacts remain audit-
    comparable, but all inputs flow through ``request`` so unit tests do not
    rely on subprocesses or argument parsing. The CLI ``run`` wrapper only
    builds the request and forwards ``args`` for provenance capture.
    """

    if not is_gurobi_available():
        raise RuntimeError(
            "Gurobi is unavailable; hourly research runs do not allow fallback"
        )

    day_ahead_result_path = Path(request.day_ahead_result_path).resolve()
    input_audit_path = day_ahead_result_path.parent / "input_audit.json"
    day_ahead_summary_path = day_ahead_result_path.parent / "summary.json"
    if not input_audit_path.is_file():
        raise ValueError(
            "The day-ahead result must have a sibling input_audit.json so its "
            "scenario, prepared input, and canonical hashes can be verified"
        )
    day_ahead_summary = _load_json(day_ahead_summary_path)
    _validate_manifest(
        "day_ahead",
        day_ahead_summary_path,
        day_ahead_summary,
    )
    rolling_git_sha, rolling_git_dirty = _git_snapshot(REPO_ROOT)
    gurobi_snapshot = _gurobi_version_snapshot()
    input_audit = _load_json(input_audit_path)
    audited_bev_terminal_policy = str(
        input_audit.get("bev_terminal_soc_policy")
        or dict(input_audit.get("terminal_soc_policy") or {}).get(
            "bev_terminal_soc_policy"
        )
        or ""
    )
    if not audited_bev_terminal_policy:
        raise ValueError(
            "Day-ahead input audit is missing bev_terminal_soc_policy"
        )
    audited_bev_terminal_policy = normalize_bev_terminal_soc_policy(
        audited_bev_terminal_policy
    ).value

    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=int(request.time_limit_sec),
        stage2_time_limit_sec=int(request.time_limit_sec),
        mip_gap=float(request.mip_gap),
        random_seed=int(request.random_seed),
        gurobi_threads=(
            None if request.gurobi_threads is None else int(request.gurobi_threads)
        ),
        research_run=True,
        allow_postsolve_repair=False,
        phase="phase1_charging_only",
        requested_phase="phase1_charging_only",
        resolved_phase="phase1_charging_only",
        executed_phase="phase1_charging_only",
    )
    if request.day_ahead_problem is not None:
        # The frontend production path must use the very same canonical object
        # that generated the persisted assignment. Rebuilding duties or input
        # rows here would create an un-auditable second interpretation.
        problem = request.day_ahead_problem
    else:
        prepared_root = _prepared_inputs_root()
        prepared_payload = load_prepared_input(
            scenario_id=request.scenario_id,
            prepared_input_id=request.prepared_input_id,
            scenarios_dir=prepared_root,
        )
        effective_scenario_name = str(
            input_audit.get("effective_scenario_artifact") or ""
        ).strip()
        effective_scenario_path = (
            input_audit_path.parent / effective_scenario_name
            if effective_scenario_name
            else None
        )
        if input_audit.get("input_fingerprint_schema") == INPUT_FINGERPRINT_SCHEMA:
            if effective_scenario_path is None or not effective_scenario_path.is_file():
                raise ValueError(
                    "Current day-ahead input audit requires effective_scenario.json"
                )
            scenario = deepcopy(_load_json(effective_scenario_path))
            expected_scenario_hash = str(
                input_audit.get("effective_scenario_sha256") or ""
            )
            actual_scenario_hash = _canonical_hash(scenario)
            if (
                not expected_scenario_hash
                or actual_scenario_hash != expected_scenario_hash
            ):
                raise ValueError(
                    "Day-ahead effective scenario hash does not match input_audit.json"
                )
        else:
            scenario = deepcopy(
                materialize_scenario_from_prepared_input(
                    store.get_scenario_document_shallow(request.scenario_id),
                    prepared_payload,
                )
            )
        simulation_config = dict(scenario.get("simulation_config") or {})
        simulation_config["bev_terminal_soc_policy"] = audited_bev_terminal_policy
        scenario["simulation_config"] = simulation_config
        scenario, weather_forecast, weather_profile = (
            _prepare_weather_policy_for_scenario(
                scenario,
                enable_weather_operation_policy=None,
                weather_proxy_forecast_path=None,
            )
        )
        enforce_research_phase3_single_continuous_duty(scenario)
        problem = ProblemBuilder().build_from_scenario(
            scenario,
            depot_id=request.depot_id,
            service_id=request.service_id,
            config=config,
            planning_days=1,
        )
        if weather_forecast is not None and weather_profile is not None:
            problem = apply_weather_policy_to_problem(
                problem,
                weather_forecast,
                weather_profile,
                random_seed=int(request.random_seed),
            )
    effective_pv_profiles, effective_pv_profiles_sha256 = (
        _load_day_ahead_effective_pv_profiles(
            day_ahead_output_dir=day_ahead_result_path.parent,
            input_audit=input_audit,
        )
    )
    problem, effective_pv_profile_audit = _apply_pv_forecast_update(
        problem,
        effective_pv_profiles,
    )
    service_date = str(problem.metadata.get("service_date") or "")[:10]
    if service_date != request.expected_service_date:
        raise ValueError(
            f"Service date mismatch: expected {request.expected_service_date}, got {service_date}"
        )

    terminal_floor_override = request.bess_terminal_min_kwh
    if terminal_floor_override is not None:
        assets = {
            str(depot_id): replace(
                asset,
                bess_terminal_soc_min_kwh=float(terminal_floor_override),
            )
            for depot_id, asset in dict(problem.depot_energy_assets or {}).items()
        }
        problem = replace(problem, depot_energy_assets=assets)

    _validate_day_ahead_input_contract(
        problem,
        input_audit,
        scenario_id=request.scenario_id,
        prepared_input_id=request.prepared_input_id,
        service_date=service_date,
        service_id=request.service_id,
    )
    day_ahead_payload = _load_json(day_ahead_result_path)
    day_ahead_plan = assignment_plan_from_serialized_result(
        problem,
        day_ahead_payload,
    )
    state = _load_json(Path(request.state_json)) if request.state_json else {}
    if int(request.execution_minutes) <= 0:
        raise ValueError("--execution-minutes must be positive")
    if request.gurobi_threads is not None and int(request.gurobi_threads) < 1:
        raise ValueError("--gurobi-threads must be positive when supplied")
    horizon_start_time = str(problem.scenario.horizon_start)
    horizon_end_time = str(problem.scenario.horizon_end)
    current_time = str(request.current_time or horizon_start_time)
    current_min = hhmm_to_min(current_time)
    state_current_min = state.get("current_min")
    if state_current_min is not None:
        absolute_state_min = int(state_current_min)
        if absolute_state_min % (24 * 60) != current_min % (24 * 60):
            raise ValueError(
                "state_json current_min does not match --current-time: "
                f"state={state_current_min}, current={current_min}"
            )
        current_min = absolute_state_min

    end_time = request.end_time
    chain_requested = bool(request.full_chain or end_time)
    if request.full_chain:
        expected_start_min = hhmm_to_min(horizon_start_time)
        if current_min % (24 * 60) != expected_start_min % (24 * 60):
            raise ValueError(
                "A formal rolling chain must begin at the day-ahead energy "
                f"horizon start {horizon_start_time}, not {current_time}"
            )
        expected_end_min = current_min + (
            len(problem.price_slots) * int(problem.scenario.timestep_min)
        )
        if end_time:
            supplied_end_min = hhmm_to_min(str(end_time))
            while supplied_end_min <= current_min:
                supplied_end_min += 24 * 60
            if supplied_end_min != expected_end_min:
                raise ValueError(
                    "A formal rolling chain must cover the full day-ahead energy "
                    f"horizon [{horizon_start_time}, {horizon_end_time}], got "
                    f"[{current_time}, {end_time}]"
                )
        end_min = expected_end_min
        end_time = horizon_end_time
    else:
        end_min = hhmm_to_min(str(end_time)) if end_time else None
        while end_min is not None and end_min <= current_min:
            end_min += 24 * 60
    if end_min is not None and end_min <= current_min:
        raise ValueError("--end-time must be later than --current-time")
    if end_min is not None and (end_min - current_min) % int(request.execution_minutes) != 0:
        raise ValueError(
            "The --current-time to --end-time interval must be divisible by "
            "--execution-minutes"
        )
    chain_start_min = current_min
    chain_start_time = _minute_label(chain_start_min)
    pv_forecast_updates = (
        _load_json(Path(request.pv_forecast_updates_json))
        if request.pv_forecast_updates_json
        else None
    )

    output_dir = Path(request.output_dir)
    rolling = RollingReoptimizer()
    summaries: list[dict[str, Any]] = []
    executed_segments: list[tuple[Any, Any, int, int]] = []
    step_index = 0
    day_ahead_assignment_hash = _day_ahead_assignment_hash(day_ahead_plan)
    day_ahead_pv_forecast_hash = _pv_forecast_hash(problem)
    day_ahead_charger_hash = _charger_configuration_hash(problem)
    input_audit_sha256 = hashlib.sha256(input_audit_path.read_bytes()).hexdigest()
    chain_failure_reason: Optional[str] = None
    while True:
        current_label = _minute_label(current_min)
        step_problem = problem
        pv_forecast_update_audit = None
        if pv_forecast_updates is not None:
            if current_label not in pv_forecast_updates:
                raise ValueError(
                    "PV forecast update file has no profile for rolling time "
                    f"{current_label}"
                )
            step_problem, pv_forecast_update_audit = _apply_pv_forecast_update(
                problem,
                pv_forecast_updates[current_label],
            )
        step_output_dir = (
            output_dir / f"step_{step_index:02d}_{current_label.replace(':', '')}"
            if end_min is not None
            else output_dir
        )
        started = time.perf_counter()
        try:
            result = rolling.reoptimize_charging_hour(
                step_problem,
                day_ahead_plan,
                config,
                current_min,
                actual_soc=dict(state.get("actual_vehicle_soc_kwh") or {}),
                actual_bess_soc_kwh=dict(state.get("actual_bess_soc_kwh") or {}),
                observed_on_peak_kw_by_depot=dict(
                    state.get("observed_on_peak_kw_by_depot") or {}
                ),
                observed_off_peak_kw_by_depot=dict(
                    state.get("observed_off_peak_kw_by_depot") or {}
                ),
                execution_minutes=int(request.execution_minutes),
                bess_terminal_policy=request.bess_terminal_policy,
            )
        except Exception as exc:
            elapsed = time.perf_counter() - started
            summary = {
                "scenario_id": request.scenario_id,
                "prepared_input_id": request.prepared_input_id,
                "service_date": service_date,
                "step_index": step_index,
                "current_time": current_label,
                "execution_minutes": int(request.execution_minutes),
                "feasible": False,
                "solver_status": "execution_error",
                "elapsed_seconds": elapsed,
                "execution_error": f"{type(exc).__name__}: {exc}",
            }
            _write_json(step_output_dir / "hourly_summary.json", summary)
            summaries.append(summary)
            chain_failure_reason = "step_execution_error"
            break
        elapsed = time.perf_counter() - started
        metadata = dict(result.solver_metadata or {})
        bess_end_by_depot = {
            str(depot_id): float(slot_map[max(slot_map)])
            for depot_id, slot_map in dict(
                result.plan.bess_soc_kwh_by_depot_slot or {}
            ).items()
            if slot_map
        }
        assignment_audit = _assert_duties_unchanged(day_ahead_assignment_hash, result)
        summary = {
            "scenario_id": request.scenario_id,
            "prepared_input_id": request.prepared_input_id,
            "service_date": service_date,
            "day_ahead_result": str(day_ahead_result_path),
            "day_ahead_input_audit": str(input_audit_path),
            "step_index": step_index,
            "current_time": current_label,
            "execution_minutes": int(request.execution_minutes),
            "lookahead": "remaining_service_day",
            "vehicle_assignment_policy": "fixed_to_persisted_day_ahead_result",
            "assignment_audit": assignment_audit,
            "day_ahead_assignment_hash": day_ahead_assignment_hash,
            "bev_terminal_soc_policy": audited_bev_terminal_policy,
            "bev_terminal_soc_target_source": metadata.get(
                "bev_terminal_soc_target_source"
            ),
            "bev_terminal_soc_target_kwh_by_vehicle": dict(
                metadata.get("vehicle_terminal_soc_target_kwh_by_vehicle") or {}
            ),
            "bev_terminal_soc_total_drawdown_kwh": metadata.get(
                "bev_terminal_soc_total_drawdown_kwh"
            ),
            "bev_terminal_soc_total_target_shortfall_kwh": metadata.get(
                "bev_terminal_soc_total_target_shortfall_kwh"
            ),
            "bev_terminal_soc_balance_satisfied": metadata.get(
                "bev_terminal_soc_balance_satisfied"
            ),
            "bess_terminal_policy": request.bess_terminal_policy,
            "bess_terminal_soc_target_source": metadata.get(
                "bess_terminal_soc_target_source"
            ),
            "bess_terminal_soc_target_kwh_by_depot": dict(
                metadata.get("bess_terminal_soc_target_kwh_by_depot") or {}
            ),
            "bess_terminal_min_kwh_override": terminal_floor_override,
            "pv_forecast_update": pv_forecast_update_audit,
            "solver_backend": gurobi_snapshot["backend"],
            "solver_version": gurobi_snapshot["version"],
            "gurobi_threads": metadata.get("gurobi_threads"),
            "time_limit_sec": int(request.time_limit_sec),
            "mip_gap": float(request.mip_gap),
            "random_seed": int(request.random_seed),
            "timestep_min": int(problem.scenario.timestep_min),
            "elapsed_seconds": elapsed,
            "solver_status": result.solver_status,
            "feasible": bool(result.feasible),
            "trip_count_served": len(result.plan.served_trip_ids),
            "trip_count_unserved": len(result.plan.unserved_trip_ids),
            "stage2_solver_status": metadata.get("stage2_solver_status"),
            "stage2_runtime_seconds": metadata.get("stage2_runtime_seconds"),
            "stage2_time_limit_sec_effective": metadata.get(
                "stage2_time_limit_sec_effective"
            ),
            "rolling_start_slot_index": metadata.get(
                "rolling_start_slot_index"
            ),
            "bess_end_soc_kwh_by_depot": bess_end_by_depot,
            "cost_breakdown": dict(result.cost_breakdown or {}),
            "warnings": list(result.warnings or ()),
            "infeasibility_reasons": list(result.infeasibility_reasons or ()),
        }
        _write_json(step_output_dir / "hourly_solver_result.json", ResultSerializer.serialize_result(result))

        if not result.feasible:
            _write_json(step_output_dir / "hourly_summary.json", summary)
            summaries.append(summary)
            chain_failure_reason = "step_infeasible"
            break

        start_slot = int(metadata.get("rolling_start_slot_index") or 0)
        executed_slot_count = int(request.execution_minutes) // max(
            int(step_problem.scenario.timestep_min), 1
        )
        stop_slot = min(start_slot + executed_slot_count, len(step_problem.price_slots))
        if not bool(assignment_audit.get("matched")):
            summary["chain_rejection_reason"] = "fixed_assignment_changed"
            _write_json(step_output_dir / "hourly_summary.json", summary)
            summaries.append(summary)
            chain_failure_reason = "fixed_assignment_changed"
            break
        executed_segments.append((step_problem, result, start_slot, stop_slot))

        next_min = current_min + int(request.execution_minutes)
        should_continue = end_min is not None and next_min < end_min
        if end_min is not None and not should_continue:
            summary["state_handoff"] = "not_required_at_chain_end"
        else:
            try:
                next_state = build_next_execution_state(
                    step_problem,
                    result,
                    current_min=current_min,
                    execution_minutes=int(request.execution_minutes),
                    prior_on_peak_kw_by_depot=dict(
                        state.get("observed_on_peak_kw_by_depot") or {}
                    ),
                    prior_off_peak_kw_by_depot=dict(
                        state.get("observed_off_peak_kw_by_depot") or {}
                    ),
                )
                state = next_state.to_dict()
                state["current_time"] = _minute_label(next_state.current_min)
                _write_json(step_output_dir / "state_for_next_hour.json", state)
                summary["state_for_next_hour"] = str(
                    step_output_dir / "state_for_next_hour.json"
                )
            except ValueError as exc:
                summary["state_handoff_error"] = str(exc)
                if should_continue:
                    _write_json(step_output_dir / "hourly_summary.json", summary)
                    summaries.append(summary)
                    chain_failure_reason = "state_handoff_failed"
                    break

        _write_json(step_output_dir / "hourly_summary.json", summary)
        summaries.append(summary)
        if chain_failure_reason:
            break
        if not should_continue:
            break
        current_min = next_min
        step_index += 1

    if chain_requested:
        try:
            executed_day_accounting = _build_executed_day_accounting(
                problem,
                day_ahead_plan,
                executed_segments,
            )
        except Exception as exc:
            executed_day_accounting = {
                "eligible": False,
                "reason": "executed_day_accounting_error",
                "rejection_reasons": [f"{type(exc).__name__}: {exc}"],
                "cost_breakdown": None,
            }
            chain_failure_reason = chain_failure_reason or "executed_day_accounting_error"
        expected_step_count = (end_min - chain_start_min) // int(request.execution_minutes)
        all_steps_feasible = bool(summaries) and all(
            bool(item.get("feasible")) for item in summaries
        )
        assignment_hash_constant = bool(summaries) and all(
            bool(step.get("assignment_audit", {}).get("matched"))
            for step in summaries
        )
        step_count_complete = len(summaries) == expected_step_count
        full_energy_horizon = bool(request.full_chain)
        acceptance_checks = {
            "full_energy_horizon_requested": full_energy_horizon,
            "all_steps_feasible": all_steps_feasible,
            "expected_step_count_observed": step_count_complete,
            "executed_day_accounting_eligible": (
                executed_day_accounting.get("eligible") is True
            ),
            "day_ahead_git_clean": input_audit.get("git_dirty") is False,
            "rolling_runner_git_clean": not rolling_git_dirty,
            "day_ahead_and_rolling_git_sha_match": bool(
                input_audit.get("git_sha")
                and rolling_git_sha
                and str(input_audit.get("git_sha")) == str(rolling_git_sha)
            ),
            "day_ahead_assignment_hash_constant": assignment_hash_constant,
            "gurobi_available": bool(gurobi_snapshot["available"]),
            "no_chain_runtime_error": chain_failure_reason is None,
        }
        rejection_reasons = [
            name for name, passed in acceptance_checks.items() if not passed
        ]
        if chain_failure_reason:
            rejection_reasons.append(chain_failure_reason)
        rejection_reasons.extend(
            str(value)
            for value in list(executed_day_accounting.get("rejection_reasons") or [])
        )
        if executed_day_accounting.get("reason"):
            rejection_reasons.append(str(executed_day_accounting["reason"]))
        chain_summary = {
            "schema_version": "rolling_chain_summary_v1",
            "scenario_id": request.scenario_id,
            "prepared_input_id": request.prepared_input_id,
            "service_date": service_date,
            "rolling_start_time": chain_start_time,
            "rolling_end_time": end_time,
            "execution_minutes": int(request.execution_minutes),
            "timestep_min": int(problem.scenario.timestep_min),
            "energy_horizon_start_time": horizon_start_time,
            "energy_horizon_end_time": horizon_end_time,
            "energy_horizon_slot_count": len(problem.price_slots),
            "expected_step_count": expected_step_count,
            "step_count": len(summaries),
            "all_steps_feasible": all_steps_feasible,
            "objective_aggregation": "not_additive_remaining_horizon_objectives",
            "remaining_day_charging_only_fixed_assignment": True,
            "day_ahead_git_sha": input_audit.get("git_sha"),
            "rolling_runner_git_sha": rolling_git_sha,
            "rolling_runner_git_dirty": rolling_git_dirty,
            "solver_backend": gurobi_snapshot["backend"],
            "solver_version": gurobi_snapshot["version"],
            "gurobi_available": bool(gurobi_snapshot["available"]),
            "gurobi_threads": (
                summaries[0].get("gurobi_threads") if summaries else None
            ),
            "time_limit_sec": int(request.time_limit_sec),
            "mip_gap": float(request.mip_gap),
            "random_seed": int(request.random_seed),
            "prepared_input_sha256": input_audit.get("prepared_input_sha256"),
            "effective_scenario_sha256": input_audit.get(
                "effective_scenario_sha256"
            ),
            "trip_input_hash": input_audit.get("trip_input_hash"),
            "vehicle_input_hash": input_audit.get("vehicle_input_hash"),
            "charger_configuration_hash": input_audit.get(
                "charger_configuration_hash"
            ),
            "initial_soc_input_hash": input_audit.get("initial_soc_input_hash"),
            "calendar_policy": input_audit.get("calendar_policy"),
            "calendar_validation_status": input_audit.get(
                "calendar_validation_status"
            ),
            "day_ahead_result_sha256": hashlib.sha256(
                day_ahead_result_path.read_bytes()
            ).hexdigest(),
            "day_ahead_input_audit_sha256": input_audit_sha256,
            "day_ahead_assignment_hash": day_ahead_assignment_hash,
            "day_ahead_pv_forecast_hash": day_ahead_pv_forecast_hash,
            "day_ahead_effective_pv_profiles_sha256": effective_pv_profiles_sha256,
            "day_ahead_effective_pv_profile_audit": effective_pv_profile_audit,
            "day_ahead_charger_hash": day_ahead_charger_hash,
            "bess_terminal_policy": request.bess_terminal_policy,
            "bev_terminal_soc_policy": audited_bev_terminal_policy,
            "executed_day_accounting": executed_day_accounting,
            "steps": summaries,
            "rejection_reasons": sorted(set(rejection_reasons)),
        }
        chain_summary["acceptance_checks"] = acceptance_checks
        chain_summary["chain_accepted"] = not chain_summary["rejection_reasons"]
        _write_json(output_dir / "rolling_chain_summary.json", chain_summary)
        _write_json(output_dir / "executed_day_accounting.json", executed_day_accounting)
        day_ahead_summary_for_compare = {
            key: _finite(day_ahead_summary.get(key))
            for key in (
                "accounting_total_cost_jpy",
                "total_cost",
                "grid_import_kwh",
                "peak_grid_kw",
                "trip_count_served",
                "trip_count_unserved",
                "used_vehicle_count",
            )
            if key in day_ahead_summary
        }
        day_ahead_vs_rolling = _build_day_ahead_vs_rolling_summary(
            day_ahead_summary=day_ahead_summary_for_compare,
            executed_day_accounting=executed_day_accounting,
            day_ahead_assignment_hash=day_ahead_assignment_hash,
            step_assignment_hashes=[
                bool(step.get("assignment_audit", {}).get("matched"))
                for step in summaries
            ],
            step_count=len(summaries),
        )
        _write_json(output_dir / "day_ahead_vs_rolling_summary.json", day_ahead_vs_rolling)
        _write_hourly_chart_csv(
            output_dir / "hourly_energy_flow_chart.csv",
            problem=problem,
            executed_segments=executed_segments,
        )
        _write_executed_charging_schedule(
            output_dir / "charging_schedule.csv",
            problem=problem,
            executed_segments=executed_segments,
        )
        print(
            json.dumps(chain_summary, ensure_ascii=False, indent=2, default=str),
            flush=True,
        )
    else:
        print(
            json.dumps(summaries[-1], ensure_ascii=False, indent=2, default=str),
            flush=True,
        )
    if chain_requested:
        return 0 if chain_summary["chain_accepted"] else 2
    return 0 if summaries and all(item["feasible"] for item in summaries) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--prepared-input-id", required=True)
    parser.add_argument("--expected-service-date", required=True)
    parser.add_argument("--day-ahead-result", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--current-time",
        default=None,
        help="Optional HH:MM; defaults to the persisted day-ahead energy horizon start.",
    )
    parser.add_argument(
        "--end-time",
        default=None,
        help=(
            "Optional chain end time. When set, repeat the remaining-day solve "
            "and execute one interval at a time until this boundary."
        ),
    )
    parser.add_argument("--execution-minutes", type=int, default=60)
    parser.add_argument("--time-limit-sec", type=int, default=30)
    parser.add_argument("--mip-gap", type=float, default=0.1)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--gurobi-threads", type=int, default=None)
    parser.add_argument("--depot-id", default="tsurumaki")
    parser.add_argument("--service-id", default="WEEKDAY")
    parser.add_argument("--state-json", default=None)
    parser.add_argument(
        "--full-chain",
        action="store_true",
        default=False,
        help=(
            "Execute and audit every slot of the day-ahead energy horizon. "
            "Only this mode can produce an accepted rolling_chain_summary.json."
        ),
    )
    parser.add_argument(
        "--pv-forecast-updates-json",
        default=None,
        help=(
            "Optional JSON object keyed by HH:MM. Each value supplies a full-"
            "horizon forecast_by_depot mapping for forecast-error experiments."
        ),
    )
    parser.add_argument(
        "--bess-terminal-policy",
        choices=("scenario", "minimum_only"),
        default="scenario",
    )
    parser.add_argument("--bess-terminal-min-kwh", type=float, default=None)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
