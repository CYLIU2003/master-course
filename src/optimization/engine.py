from __future__ import annotations

from dataclasses import replace

from src.optimization.abc.engine import ABCOptimizer
from src.optimization.alns.engine import ALNSOptimizer
from src.optimization.common.charging_topup import apply_opportunistic_topup
from src.optimization.common.bess_terminal_policy import (
    resolve_bess_terminal_soc_target_kwh,
)
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
    PHASE_ALIASES,
    VALID_PHASES,
    normalize_phase,
)
from src.optimization.common.benchmarking import solver_benchmark_eligibility
from src.optimization.common.strict_precheck import (
    StrictCoveragePrecheckResult,
    evaluate_strict_coverage_precheck,
)
from src.optimization.common.vehicle_assignment import assign_duty_fragments_to_vehicles
from src.optimization.common.time_axis import service_minute
from src.optimization.ga.engine import GAOptimizer
from src.optimization.hybrid.hybrid_engine import HybridOptimizer
from src.optimization.milp.engine import MILPOptimizer


def _normalize_depot_slot_flow_mapping(raw: object) -> dict[str, dict[int, float]]:
    normalized: dict[str, dict[int, float]] = {}
    if not isinstance(raw, dict):
        return normalized
    for depot_id, slot_map in raw.items():
        depot_key = str(depot_id or "").strip()
        if not depot_key:
            continue
        normalized_slot_map: dict[int, float] = {}
        items = slot_map.items() if isinstance(slot_map, dict) else dict(slot_map or {}).items()
        for slot_idx, value in items:
            try:
                slot_key = int(slot_idx)
            except (TypeError, ValueError):
                continue
            try:
                amount = float(value or 0.0)
            except (TypeError, ValueError):
                amount = 0.0
            if amount > 0.0:
                normalized_slot_map[slot_key] = amount
        if normalized_slot_map:
            normalized[depot_key] = normalized_slot_map
    return normalized


def _charging_slot_signature(charging_slot) -> tuple[str, int, str, str]:
    return (
        str(getattr(charging_slot, "vehicle_id", "") or ""),
        int(getattr(charging_slot, "slot_index", 0) or 0),
        str(getattr(charging_slot, "charger_id", "") or ""),
        str(getattr(charging_slot, "charging_depot_id", "") or ""),
    )


def _capture_source_flow_context(plan: AssignmentPlan) -> dict[str, object]:
    metadata = dict(getattr(plan, "metadata", {}) or {})
    grid_to_bus = _normalize_depot_slot_flow_mapping(getattr(plan, "grid_to_bus_kwh_by_depot_slot", {}))
    pv_to_bus = _normalize_depot_slot_flow_mapping(getattr(plan, "pv_to_bus_kwh_by_depot_slot", {}))
    bess_to_bus = _normalize_depot_slot_flow_mapping(getattr(plan, "bess_to_bus_kwh_by_depot_slot", {}))
    pv_to_bess = _normalize_depot_slot_flow_mapping(getattr(plan, "pv_to_bess_kwh_by_depot_slot", {}))
    grid_to_bess = _normalize_depot_slot_flow_mapping(getattr(plan, "grid_to_bess_kwh_by_depot_slot", {}))
    pv_curtail = _normalize_depot_slot_flow_mapping(getattr(plan, "pv_curtail_kwh_by_depot_slot", {}))
    bess_soc = _normalize_depot_slot_flow_mapping(getattr(plan, "bess_soc_kwh_by_depot_slot", {}))
    bess_soc_start = _normalize_depot_slot_flow_mapping(metadata.get("bess_soc_start_kwh_by_depot_slot", {}))
    bess_soc_end = _normalize_depot_slot_flow_mapping(metadata.get("bess_soc_end_kwh_by_depot_slot", {}))
    contract_over_limit = _normalize_depot_slot_flow_mapping(getattr(plan, "contract_over_limit_kwh_by_depot_slot", {}))
    explicit_source_split = any(
        max(float(value or 0.0), 0.0) > 0.0
        for mapping in (grid_to_bus, pv_to_bus, bess_to_bus, pv_to_bess, grid_to_bess, pv_curtail)
        for slot_map in mapping.values()
        for value in slot_map.values()
    )
    return {
        "grid_to_bus_kwh_by_depot_slot": grid_to_bus,
        "pv_to_bus_kwh_by_depot_slot": pv_to_bus,
        "bess_to_bus_kwh_by_depot_slot": bess_to_bus,
        "pv_to_bess_kwh_by_depot_slot": pv_to_bess,
        "grid_to_bess_kwh_by_depot_slot": grid_to_bess,
        "pv_curtail_kwh_by_depot_slot": pv_curtail,
        "bess_soc_kwh_by_depot_slot": bess_soc,
        "bess_soc_start_kwh_by_depot_slot": bess_soc_start,
        "bess_soc_end_kwh_by_depot_slot": bess_soc_end or bess_soc,
        "contract_over_limit_kwh_by_depot_slot": contract_over_limit,
        "source_provenance_exact": explicit_source_split,
        "charging_slot_signatures": tuple(_charging_slot_signature(slot) for slot in list(getattr(plan, "charging_slots", ()) or ())),
    }


def _source_flow_context_has_positive_flow(source_flow_context: dict[str, object]) -> bool:
    return any(
        max(float(value or 0.0), 0.0) > 0.0
        for key in (
            "grid_to_bus_kwh_by_depot_slot",
            "pv_to_bus_kwh_by_depot_slot",
            "bess_to_bus_kwh_by_depot_slot",
            "pv_to_bess_kwh_by_depot_slot",
            "grid_to_bess_kwh_by_depot_slot",
            "pv_curtail_kwh_by_depot_slot",
        )
        for slot_map in _normalize_depot_slot_flow_mapping(source_flow_context.get(key, {})).values()
        for value in slot_map.values()
    )


def _vehicle_home_depot_by_id(problem: CanonicalOptimizationProblem) -> dict[str, str]:
    return {
        str(getattr(vehicle, "vehicle_id", "") or ""): str(getattr(vehicle, "home_depot_id", "") or "")
        for vehicle in list(getattr(problem, "vehicles", ()) or ())
        if str(getattr(vehicle, "vehicle_id", "") or "")
    }


def _fallback_depot_id(problem: CanonicalOptimizationProblem) -> str:
    for depot in list(getattr(problem, "depots", ()) or ()):
        depot_id = str(getattr(depot, "depot_id", "") or "").strip()
        if depot_id:
            return depot_id
    for depot_id in dict(getattr(problem, "depot_energy_assets", {}) or {}).keys():
        depot_key = str(depot_id or "").strip()
        if depot_key:
            return depot_key
    return "depot_default"


def _charging_source_and_depot(
    problem: CanonicalOptimizationProblem,
    charging_slot,
    vehicle_home_depot: dict[str, str] | None = None,
) -> tuple[str, str]:
    fallback_depot = (
        dict(vehicle_home_depot or {}).get(str(getattr(charging_slot, "vehicle_id", "") or ""))
        or str(getattr(charging_slot, "charging_depot_id", "") or "")
        or _fallback_depot_id(problem)
    )
    explicit_source = str(
        getattr(charging_slot, "energy_source", "") or ""
    ).strip().lower()
    explicit_depot = str(
        getattr(charging_slot, "charging_depot_id", "") or ""
    ).strip()
    if explicit_source in {"grid", "pv", "bess"}:
        return explicit_source, explicit_depot or fallback_depot
    charger_id = str(getattr(charging_slot, "charger_id", "") or "").strip()
    if ":" in charger_id:
        source, depot_id = charger_id.split(":", 1)
        source_key = source.strip().lower()
        if source_key in {"grid", "pv", "bess"}:
            return source_key, depot_id.strip() or fallback_depot
    depot_id = str(getattr(charging_slot, "charging_depot_id", "") or "").strip()
    return "grid", depot_id or fallback_depot


def _merge_source_context_with_added_charging(
    problem: CanonicalOptimizationProblem,
    plan: AssignmentPlan,
    source_flow_context: dict[str, object],
) -> AssignmentPlan:
    timestep_h = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1) / 60.0
    vehicle_home_depot = _vehicle_home_depot_by_id(problem)
    charging_signatures = {
        tuple(item)
        for item in list(source_flow_context.get("charging_slot_signatures") or [])
        if isinstance(item, (list, tuple)) and len(item) >= 4
    }
    grid_to_bus = _normalize_depot_slot_flow_mapping(source_flow_context.get("grid_to_bus_kwh_by_depot_slot", {}))
    pv_to_bus = _normalize_depot_slot_flow_mapping(source_flow_context.get("pv_to_bus_kwh_by_depot_slot", {}))
    bess_to_bus = _normalize_depot_slot_flow_mapping(source_flow_context.get("bess_to_bus_kwh_by_depot_slot", {}))
    added_kwh = 0.0
    for charging_slot in list(getattr(plan, "charging_slots", ()) or ()):
        if _charging_slot_signature(charging_slot) in charging_signatures:
            continue
        charge_kw = max(float(getattr(charging_slot, "charge_kw", 0.0) or 0.0), 0.0)
        discharge_kw = max(float(getattr(charging_slot, "discharge_kw", 0.0) or 0.0), 0.0)
        net_charge_kwh = max(charge_kw - discharge_kw, 0.0) * timestep_h
        if net_charge_kwh <= 1.0e-9:
            continue
        source, depot_id = _charging_source_and_depot(problem, charging_slot, vehicle_home_depot)
        target = grid_to_bus
        if source == "pv":
            target = pv_to_bus
        elif source == "bess":
            target = bess_to_bus
        slot_idx = int(getattr(charging_slot, "slot_index", 0) or 0)
        slot_map = target.setdefault(str(depot_id), {})
        slot_map[slot_idx] = slot_map.get(slot_idx, 0.0) + net_charge_kwh
        added_kwh += net_charge_kwh
    source_provenance_exact = bool(source_flow_context.get("source_provenance_exact")) and added_kwh <= 1.0e-9
    metadata = dict(plan.metadata or {})
    metadata["source_provenance_exact"] = source_provenance_exact
    metadata["vehicle_source_provenance_exact"] = bool(metadata.get("vehicle_source_provenance_exact")) and source_provenance_exact
    metadata["derived_source_split"] = not source_provenance_exact
    metadata["canonical_source_flow_context"] = {
        **source_flow_context,
        "grid_to_bus_kwh_by_depot_slot": grid_to_bus,
        "pv_to_bus_kwh_by_depot_slot": pv_to_bus,
        "bess_to_bus_kwh_by_depot_slot": bess_to_bus,
        "source_provenance_exact": source_provenance_exact,
        "source_provenance_note": (
            "Preserved exact pre-postsolve per-source flow maps."
            if source_provenance_exact
            else "Preserved pre-postsolve flow maps and added postsolve charging as derived source flow."
        ),
        "charging_slot_signatures": tuple(
            _charging_slot_signature(slot) for slot in list(getattr(plan, "charging_slots", ()) or ())
        ),
    }
    merged_plan = replace(
        plan,
        grid_to_bus_kwh_by_depot_slot=grid_to_bus,
        pv_to_bus_kwh_by_depot_slot=pv_to_bus,
        bess_to_bus_kwh_by_depot_slot=bess_to_bus,
        pv_to_bess_kwh_by_depot_slot=_normalize_depot_slot_flow_mapping(source_flow_context.get("pv_to_bess_kwh_by_depot_slot", {})),
        grid_to_bess_kwh_by_depot_slot=_normalize_depot_slot_flow_mapping(source_flow_context.get("grid_to_bess_kwh_by_depot_slot", {})),
        pv_curtail_kwh_by_depot_slot=_normalize_depot_slot_flow_mapping(source_flow_context.get("pv_curtail_kwh_by_depot_slot", {})),
        bess_soc_kwh_by_depot_slot=_normalize_depot_slot_flow_mapping(source_flow_context.get("bess_soc_kwh_by_depot_slot", {})),
        contract_over_limit_kwh_by_depot_slot=_normalize_depot_slot_flow_mapping(source_flow_context.get("contract_over_limit_kwh_by_depot_slot", {})),
        metadata=metadata,
    )
    return _repair_bess_terminal_soc(problem, merged_plan)


def _set_positive_slot_value(mapping: dict[str, dict[int, float]], depot_id: str, slot_idx: int, value: float) -> None:
    slot_map = mapping.setdefault(depot_id, {})
    if value > 1.0e-9:
        slot_map[slot_idx] = value
    else:
        slot_map.pop(slot_idx, None)
        if not slot_map:
            mapping.pop(depot_id, None)


def _bess_soc_max_kwh(asset) -> float:
    capacity = max(float(getattr(asset, "bess_energy_kwh", 0.0) or 0.0), 0.0)
    configured_max = max(float(getattr(asset, "bess_soc_max_kwh", 0.0) or 0.0), 0.0)
    if configured_max > 0.0:
        return min(configured_max, capacity) if capacity > 0.0 else configured_max
    return capacity


def _bess_terminal_soc_target(asset, *, min_soc: float, max_soc: float) -> float | None:
    return resolve_bess_terminal_soc_target_kwh(
        policy=getattr(asset, "bess_terminal_soc_policy", ""),
        initial_soc_kwh=float(getattr(asset, "bess_initial_soc_kwh", 0.0) or 0.0),
        configured_target_kwh=float(
            getattr(asset, "bess_terminal_soc_target_kwh", 0.0) or 0.0
        ),
        terminal_soc_floor_kwh=min_soc,
        maximum_soc_kwh=max_soc,
    )


def _repair_bess_terminal_soc(
    problem: CanonicalOptimizationProblem,
    plan: AssignmentPlan,
) -> AssignmentPlan:
    """Shift late BESS discharge back to grid when terminal SOC would be violated."""

    assets = dict(getattr(problem, "depot_energy_assets", {}) or {})
    if not assets:
        return plan

    grid_to_bus = _normalize_depot_slot_flow_mapping(getattr(plan, "grid_to_bus_kwh_by_depot_slot", {}))
    pv_to_bus = _normalize_depot_slot_flow_mapping(getattr(plan, "pv_to_bus_kwh_by_depot_slot", {}))
    bess_to_bus = _normalize_depot_slot_flow_mapping(getattr(plan, "bess_to_bus_kwh_by_depot_slot", {}))
    pv_to_bess = _normalize_depot_slot_flow_mapping(getattr(plan, "pv_to_bess_kwh_by_depot_slot", {}))
    grid_to_bess = _normalize_depot_slot_flow_mapping(getattr(plan, "grid_to_bess_kwh_by_depot_slot", {}))
    pv_curtail = _normalize_depot_slot_flow_mapping(getattr(plan, "pv_curtail_kwh_by_depot_slot", {}))
    contract_over_limit = _normalize_depot_slot_flow_mapping(getattr(plan, "contract_over_limit_kwh_by_depot_slot", {}))
    bess_soc: dict[str, dict[int, float]] = {}
    bess_soc_start: dict[str, dict[int, float]] = {}
    bess_soc_end: dict[str, dict[int, float]] = {}

    timestep_h = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1) / 60.0
    depot_limit_kw = {
        str(getattr(depot, "depot_id", "") or ""): float(getattr(depot, "import_limit_kw", 0.0) or 0.0)
        for depot in list(getattr(problem, "depots", ()) or ())
        if str(getattr(depot, "depot_id", "") or "")
    }
    shifted_to_grid_kwh = 0.0
    bess_soc_boundary_adjusted_kwh = 0.0
    remaining_violation_kwh = 0.0
    terminal_target_by_depot: dict[str, float] = {}
    terminal_deviation_by_depot: dict[str, float] = {}

    for depot_id, asset in assets.items():
        depot_key = str(depot_id)
        if not bool(getattr(asset, "bess_enabled", False)):
            continue
        max_soc = _bess_soc_max_kwh(asset)
        if max_soc <= 1.0e-9:
            continue
        min_soc = min(max(float(getattr(asset, "bess_soc_min_kwh", 0.0) or 0.0), 0.0), max_soc)
        initial_soc = min(max(float(getattr(asset, "bess_initial_soc_kwh", 0.0) or 0.0), min_soc), max_soc)
        terminal_min = min(
            max(float(getattr(asset, "bess_terminal_soc_min_kwh", 0.0) or 0.0), min_soc),
            max_soc,
        )
        terminal_target = _bess_terminal_soc_target(asset, min_soc=min_soc, max_soc=max_soc)
        if terminal_target is not None:
            terminal_target_by_depot[depot_key] = terminal_target
        discharge_eff = min(max(float(getattr(asset, "bess_discharge_efficiency", 0.95) or 0.95), 1.0e-9), 1.0)
        charge_eff = min(max(float(getattr(asset, "bess_charge_efficiency", 0.95) or 0.95), 1.0e-9), 1.0)
        slot_indices = set()
        for mapping in (grid_to_bus, pv_to_bus, bess_to_bus, pv_to_bess, grid_to_bess, pv_curtail):
            slot_indices.update((mapping.get(depot_key, {}) or {}).keys())
        pv_series = tuple(getattr(asset, "pv_generation_kwh_by_slot", ()) or ())
        slot_indices.update(range(len(pv_series)))
        if not slot_indices:
            continue

        def _apply_bess_soc_limits() -> tuple[float, dict[int, float], dict[int, float]]:
            nonlocal bess_soc_boundary_adjusted_kwh, shifted_to_grid_kwh
            soc = initial_soc
            soc_start_by_slot: dict[int, float] = {}
            soc_end_by_slot: dict[int, float] = {}
            for slot_idx in sorted(int(idx) for idx in slot_indices):
                soc_start_by_slot[slot_idx] = soc
                discharge_bus = max(float((bess_to_bus.get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
                discharge_limit = max((soc - min_soc) * discharge_eff, 0.0)
                if discharge_bus > discharge_limit + 1.0e-9:
                    reduced = discharge_bus - discharge_limit
                    _set_positive_slot_value(bess_to_bus, depot_key, slot_idx, discharge_limit)
                    grid_slot_value = max(float((grid_to_bus.get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
                    _set_positive_slot_value(grid_to_bus, depot_key, slot_idx, grid_slot_value + reduced)
                    shifted_to_grid_kwh += reduced
                    bess_soc_boundary_adjusted_kwh += reduced
                    discharge_bus = discharge_limit
                soc_after_discharge = max(min_soc, soc - (discharge_bus / discharge_eff))

                pv_charge = max(float((pv_to_bess.get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
                grid_charge = max(float((grid_to_bess.get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
                charge_input = pv_charge + grid_charge
                charge_limit = max((max_soc - soc_after_discharge) / charge_eff, 0.0)
                if charge_input > charge_limit + 1.0e-9:
                    excess = charge_input - charge_limit
                    grid_reduction = min(grid_charge, excess)
                    if grid_reduction > 1.0e-9:
                        grid_charge -= grid_reduction
                        excess -= grid_reduction
                        bess_soc_boundary_adjusted_kwh += grid_reduction
                        _set_positive_slot_value(grid_to_bess, depot_key, slot_idx, grid_charge)
                    pv_reduction = min(pv_charge, excess)
                    if pv_reduction > 1.0e-9:
                        pv_charge -= pv_reduction
                        excess -= pv_reduction
                        bess_soc_boundary_adjusted_kwh += pv_reduction
                        _set_positive_slot_value(pv_to_bess, depot_key, slot_idx, pv_charge)
                        curtail_slot_value = max(float((pv_curtail.get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
                        _set_positive_slot_value(pv_curtail, depot_key, slot_idx, curtail_slot_value + pv_reduction)
                    charge_input = pv_charge + grid_charge
                soc = min(max_soc, max(min_soc, soc_after_discharge + charge_input * charge_eff))
                soc_end_by_slot[slot_idx] = soc
            return soc, soc_start_by_slot, soc_end_by_slot

        final_soc, soc_start_by_slot, soc_by_slot = _apply_bess_soc_limits()
        shortage = max(terminal_min - final_soc, 0.0)
        if shortage > 1.0e-9:
            for slot_idx in sorted((bess_to_bus.get(depot_key, {}) or {}).keys(), reverse=True):
                if shortage <= 1.0e-9:
                    break
                current_bess_to_bus = max(float((bess_to_bus.get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
                reducible = min(current_bess_to_bus, shortage * discharge_eff)
                if reducible <= 1.0e-9:
                    continue
                _set_positive_slot_value(bess_to_bus, depot_key, slot_idx, current_bess_to_bus - reducible)
                grid_slot_value = max(float((grid_to_bus.get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
                _set_positive_slot_value(grid_to_bus, depot_key, slot_idx, grid_slot_value + reducible)
                shifted_to_grid_kwh += reducible
                bess_soc_boundary_adjusted_kwh += reducible
                shortage -= reducible / discharge_eff
            final_soc, soc_start_by_slot, soc_by_slot = _apply_bess_soc_limits()
            shortage = max(terminal_min - final_soc, 0.0)
        remaining_violation_kwh += shortage
        if terminal_target is not None:
            terminal_deviation_by_depot[depot_key] = abs(final_soc - terminal_target)
        for slot_idx, soc_value in soc_by_slot.items():
            _set_positive_slot_value(bess_soc, depot_key, slot_idx, soc_value)
            _set_positive_slot_value(bess_soc_start, depot_key, slot_idx, soc_start_by_slot.get(slot_idx, initial_soc))
            _set_positive_slot_value(bess_soc_end, depot_key, slot_idx, soc_value)
            contract_limit_kwh = max(float(depot_limit_kw.get(depot_key, 0.0) or 0.0), 0.0) * timestep_h
            grid_import_kwh = max(float((grid_to_bus.get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
            grid_import_kwh += max(float((grid_to_bess.get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
            contract_over = max(grid_import_kwh - contract_limit_kwh, 0.0) if contract_limit_kwh > 0.0 else 0.0
            _set_positive_slot_value(contract_over_limit, depot_key, slot_idx, contract_over)

    metadata = dict(plan.metadata or {})
    metadata["bess_terminal_soc_repair_shifted_to_grid_kwh"] = float(shifted_to_grid_kwh)
    metadata["bess_soc_boundary_adjusted_kwh"] = float(bess_soc_boundary_adjusted_kwh)
    metadata["bess_terminal_soc_violation_kwh"] = float(max(remaining_violation_kwh, 0.0))
    metadata["bess_terminal_soc_target_kwh_by_depot"] = terminal_target_by_depot
    metadata["bess_terminal_soc_deviation_kwh_by_depot"] = terminal_deviation_by_depot
    metadata["bess_terminal_soc_deviation_kwh"] = float(sum(terminal_deviation_by_depot.values()))
    metadata["bess_soc_start_kwh_by_depot_slot"] = bess_soc_start
    metadata["bess_soc_end_kwh_by_depot_slot"] = bess_soc_end or bess_soc
    metadata["canonical_source_flow_context"] = {
        **dict(metadata.get("canonical_source_flow_context") or {}),
        "grid_to_bus_kwh_by_depot_slot": grid_to_bus,
        "pv_to_bus_kwh_by_depot_slot": pv_to_bus,
        "bess_to_bus_kwh_by_depot_slot": bess_to_bus,
        "pv_to_bess_kwh_by_depot_slot": pv_to_bess,
        "grid_to_bess_kwh_by_depot_slot": grid_to_bess,
        "pv_curtail_kwh_by_depot_slot": pv_curtail,
        "bess_soc_kwh_by_depot_slot": bess_soc,
        "bess_soc_start_kwh_by_depot_slot": bess_soc_start,
        "bess_soc_end_kwh_by_depot_slot": bess_soc_end or bess_soc,
        "contract_over_limit_kwh_by_depot_slot": contract_over_limit,
        "bess_terminal_soc_target_kwh_by_depot": terminal_target_by_depot,
        "bess_terminal_soc_deviation_kwh_by_depot": terminal_deviation_by_depot,
    }
    if bess_soc_boundary_adjusted_kwh <= 1.0e-9 and shifted_to_grid_kwh <= 1.0e-9 and remaining_violation_kwh <= 1.0e-9:
        return replace(plan, bess_soc_kwh_by_depot_slot=bess_soc or getattr(plan, "bess_soc_kwh_by_depot_slot", {}), metadata=metadata)
    derived_plan = replace(
        plan,
        grid_to_bus_kwh_by_depot_slot=grid_to_bus,
        pv_to_bus_kwh_by_depot_slot=pv_to_bus,
        bess_to_bus_kwh_by_depot_slot=bess_to_bus,
        pv_to_bess_kwh_by_depot_slot=pv_to_bess,
        grid_to_bess_kwh_by_depot_slot=grid_to_bess,
        pv_curtail_kwh_by_depot_slot=pv_curtail,
        bess_soc_kwh_by_depot_slot=bess_soc,
        contract_over_limit_kwh_by_depot_slot=contract_over_limit,
        metadata=metadata,
    )
    return derived_plan


def _derive_depot_energy_source_split(
    problem: CanonicalOptimizationProblem,
    plan: AssignmentPlan,
) -> AssignmentPlan:
    timestep_h = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1) / 60.0
    vehicle_home_depot = _vehicle_home_depot_by_id(problem)
    bus_demand_by_depot_slot: dict[str, dict[int, float]] = {}
    for charging_slot in list(getattr(plan, "charging_slots", ()) or ()):
        charge_kw = max(float(getattr(charging_slot, "charge_kw", 0.0) or 0.0), 0.0)
        discharge_kw = max(float(getattr(charging_slot, "discharge_kw", 0.0) or 0.0), 0.0)
        net_charge_kwh = max(charge_kw - discharge_kw, 0.0) * timestep_h
        if net_charge_kwh <= 1.0e-9:
            continue
        _source, depot_id = _charging_source_and_depot(problem, charging_slot, vehicle_home_depot)
        slot_idx = int(getattr(charging_slot, "slot_index", 0) or 0)
        slot_map = bus_demand_by_depot_slot.setdefault(str(depot_id), {})
        slot_map[slot_idx] = slot_map.get(slot_idx, 0.0) + net_charge_kwh

    depot_ids = set(bus_demand_by_depot_slot.keys())
    depot_ids.update(str(key) for key in dict(getattr(problem, "depot_energy_assets", {}) or {}).keys())
    depot_ids.update(str(getattr(depot, "depot_id", "") or "") for depot in list(getattr(problem, "depots", ()) or ()))
    depot_ids = {item for item in depot_ids if item}
    if not depot_ids:
        return plan

    depot_limit_kw = {
        str(getattr(depot, "depot_id", "") or ""): float(getattr(depot, "import_limit_kw", 0.0) or 0.0)
        for depot in list(getattr(problem, "depots", ()) or ())
        if str(getattr(depot, "depot_id", "") or "")
    }
    max_slot = max((int(slot.slot_index) for slot in list(getattr(problem, "price_slots", ()) or ())), default=-1)
    for slot_map in bus_demand_by_depot_slot.values():
        max_slot = max(max_slot, max((int(slot_idx) for slot_idx in slot_map.keys()), default=-1))
    for asset in dict(getattr(problem, "depot_energy_assets", {}) or {}).values():
        max_slot = max(max_slot, len(tuple(getattr(asset, "pv_generation_kwh_by_slot", ()) or ())) - 1)
    if max_slot < 0:
        return plan

    grid_to_bus: dict[str, dict[int, float]] = {}
    pv_to_bus: dict[str, dict[int, float]] = {}
    bess_to_bus: dict[str, dict[int, float]] = {}
    pv_to_bess: dict[str, dict[int, float]] = {}
    grid_to_bess: dict[str, dict[int, float]] = {}
    pv_curtail: dict[str, dict[int, float]] = {}
    bess_soc: dict[str, dict[int, float]] = {}
    bess_soc_start: dict[str, dict[int, float]] = {}
    bess_soc_end: dict[str, dict[int, float]] = {}
    contract_over_limit: dict[str, dict[int, float]] = {}
    terminal_target_by_depot: dict[str, float] = {}
    terminal_deviation_by_depot: dict[str, float] = {}

    for depot_id in sorted(depot_ids):
        asset = dict(getattr(problem, "depot_energy_assets", {}) or {}).get(depot_id)
        pv_generation = tuple(getattr(asset, "pv_generation_kwh_by_slot", ()) or ()) if asset is not None else ()
        bess_enabled = bool(getattr(asset, "bess_enabled", False)) if asset is not None else False
        max_soc = _bess_soc_max_kwh(asset) if asset is not None else 0.0
        min_soc = min(max(float(getattr(asset, "bess_soc_min_kwh", 0.0) or 0.0), 0.0), max_soc)
        initial_soc = min(max(float(getattr(asset, "bess_initial_soc_kwh", 0.0) or 0.0), min_soc), max_soc)
        terminal_target = _bess_terminal_soc_target(asset, min_soc=min_soc, max_soc=max_soc) if asset is not None else None
        if bess_enabled and terminal_target is not None:
            terminal_target_by_depot[depot_id] = terminal_target
        power_kwh = max(float(getattr(asset, "bess_power_kw", 0.0) or 0.0), 0.0) * timestep_h if asset is not None else 0.0
        charge_eff = min(max(float(getattr(asset, "bess_charge_efficiency", 0.95) or 0.95), 1.0e-9), 1.0)
        discharge_eff = min(max(float(getattr(asset, "bess_discharge_efficiency", 0.95) or 0.95), 1.0e-9), 1.0)
        if max_soc <= 1.0e-9 or power_kwh <= 1.0e-9:
            bess_enabled = False
        soc = initial_soc
        for slot_idx in range(max_slot + 1):
            soc_start = soc
            bus_demand = max(float(bus_demand_by_depot_slot.get(depot_id, {}).get(slot_idx, 0.0) or 0.0), 0.0)
            pv_available = max(float(pv_generation[slot_idx] if slot_idx < len(pv_generation) else 0.0), 0.0)
            pv_to_bus_kwh = min(bus_demand, pv_available)
            if pv_to_bus_kwh > 1.0e-9:
                bus_demand -= pv_to_bus_kwh
                pv_available -= pv_to_bus_kwh
            bess_to_bus_kwh = 0.0
            if bess_enabled and bus_demand > 1.0e-9:
                discharge_floor = max(min_soc, terminal_target) if terminal_target is not None else min_soc
                available_to_bus = max((soc - discharge_floor) * discharge_eff, 0.0)
                bess_to_bus_kwh = min(bus_demand, power_kwh, available_to_bus)
                if bess_to_bus_kwh > 1.0e-9:
                    soc = max(discharge_floor, soc - (bess_to_bus_kwh / discharge_eff))
                    bus_demand -= bess_to_bus_kwh
            grid_to_bus_kwh = max(bus_demand, 0.0)
            pv_to_bess_kwh = 0.0
            if bess_enabled and pv_available > 1.0e-9:
                available_input = max((max_soc - soc) / charge_eff, 0.0)
                pv_to_bess_kwh = min(pv_available, power_kwh, available_input)
                if pv_to_bess_kwh > 1.0e-9:
                    soc = min(max_soc, soc + pv_to_bess_kwh * charge_eff)
                    pv_available -= pv_to_bess_kwh
            pv_curtail_kwh = max(pv_available, 0.0)
            contract_limit = max(float(depot_limit_kw.get(depot_id, 0.0) or 0.0), 0.0) * timestep_h
            contract_over_kwh = max(grid_to_bus_kwh - contract_limit, 0.0) if contract_limit > 0.0 else 0.0

            def _set(mapping: dict[str, dict[int, float]], value: float) -> None:
                if value > 1.0e-9:
                    mapping.setdefault(depot_id, {})[slot_idx] = value

            _set(grid_to_bus, grid_to_bus_kwh)
            _set(pv_to_bus, pv_to_bus_kwh)
            _set(bess_to_bus, bess_to_bus_kwh)
            _set(pv_to_bess, pv_to_bess_kwh)
            _set(pv_curtail, pv_curtail_kwh)
            _set(contract_over_limit, contract_over_kwh)
            if bess_enabled:
                bess_soc_start.setdefault(depot_id, {})[slot_idx] = soc_start
                bess_soc.setdefault(depot_id, {})[slot_idx] = soc
                bess_soc_end.setdefault(depot_id, {})[slot_idx] = soc
        if bess_enabled and terminal_target is not None:
            terminal_deviation_by_depot[depot_id] = abs(soc - terminal_target)

    metadata = dict(plan.metadata or {})
    metadata["derived_source_split"] = True
    metadata["source_provenance_exact"] = False
    metadata["vehicle_source_provenance_exact"] = False
    metadata["bess_terminal_soc_target_kwh_by_depot"] = terminal_target_by_depot
    metadata["bess_terminal_soc_deviation_kwh_by_depot"] = terminal_deviation_by_depot
    metadata["bess_terminal_soc_deviation_kwh"] = float(sum(terminal_deviation_by_depot.values()))
    metadata["bess_soc_start_kwh_by_depot_slot"] = bess_soc_start
    metadata["bess_soc_end_kwh_by_depot_slot"] = bess_soc_end or bess_soc
    metadata["canonical_source_flow_context"] = {
        "grid_to_bus_kwh_by_depot_slot": grid_to_bus,
        "pv_to_bus_kwh_by_depot_slot": pv_to_bus,
        "bess_to_bus_kwh_by_depot_slot": bess_to_bus,
        "pv_to_bess_kwh_by_depot_slot": pv_to_bess,
        "grid_to_bess_kwh_by_depot_slot": grid_to_bess,
        "pv_curtail_kwh_by_depot_slot": pv_curtail,
        "bess_soc_kwh_by_depot_slot": bess_soc,
        "bess_soc_start_kwh_by_depot_slot": bess_soc_start,
        "bess_soc_end_kwh_by_depot_slot": bess_soc_end or bess_soc,
        "contract_over_limit_kwh_by_depot_slot": contract_over_limit,
        "bess_terminal_soc_target_kwh_by_depot": terminal_target_by_depot,
        "bess_terminal_soc_deviation_kwh_by_depot": terminal_deviation_by_depot,
        "source_provenance_exact": False,
        "derived_source_split": True,
        "source_provenance_note": (
            "Deterministic postsolve source split derived from charging demand, PV generation, and BESS limits. "
            "It is not a MILP decision trace."
        ),
        "charging_slot_signatures": tuple(
            _charging_slot_signature(slot) for slot in list(getattr(plan, "charging_slots", ()) or ())
        ),
    }
    derived_plan = replace(
        plan,
        grid_to_bus_kwh_by_depot_slot=grid_to_bus,
        pv_to_bus_kwh_by_depot_slot=pv_to_bus,
        bess_to_bus_kwh_by_depot_slot=bess_to_bus,
        pv_to_bess_kwh_by_depot_slot=pv_to_bess,
        grid_to_bess_kwh_by_depot_slot=grid_to_bess,
        pv_curtail_kwh_by_depot_slot=pv_curtail,
        bess_soc_kwh_by_depot_slot=bess_soc,
        contract_over_limit_kwh_by_depot_slot=contract_over_limit,
        metadata=metadata,
    )
    return _repair_bess_terminal_soc(problem, derived_plan)


class OptimizationEngine:
    def __init__(self) -> None:
        self._milp = MILPOptimizer()
        self._alns = ALNSOptimizer()
        self._ga = GAOptimizer()
        self._abc = ABCOptimizer()
        self._hybrid = HybridOptimizer()
        self._feasibility = FeasibilityChecker()
        self._evaluator = CostEvaluator()

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> OptimizationEngineResult:
        problem, config = self._apply_phase_contract(problem, config)
        precheck = evaluate_strict_coverage_precheck(problem)
        if precheck.infeasible and not bool(getattr(config, "debug_mode", False)):
            result = self._strict_precheck_infeasible_result(problem, config, precheck)
            return self._finalize_result(problem, result, config)

        # The strict path-cover precheck is already paid for at this point.
        # Preserve its valid relaxed lower bound so the MILP can add an
        # explicit aggregate vehicle-count cut instead of rediscovering the
        # same bound through a very weak disaggregated LP relaxation.
        problem = replace(
            problem,
            metadata={
                **dict(problem.metadata or {}),
                "strict_coverage_precheck": precheck.to_metadata(),
            },
        )

        if config.mode == OptimizationMode.MILP:
            result = self._milp.solve(problem, config)
        elif config.mode == OptimizationMode.ALNS:
            result = self._alns.solve(problem, config)
        elif config.mode == OptimizationMode.GA:
            result = self._ga.solve(problem, config)
        elif config.mode == OptimizationMode.ABC:
            result = self._abc.solve(problem, config)
        else:
            result = self._hybrid.solve(problem, config)
        return self._finalize_result(problem, result, config)

    @staticmethod
    def _apply_phase_contract(
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> tuple[CanonicalOptimizationProblem, OptimizationConfig]:
        """Make public phase safety rules hold for every engine caller.

        BFF routing is only one entry point: rolling re-optimization and scripts
        call this engine directly.  Explicit phase tokens therefore own their
        no-repair/debug semantics here instead of relying on a caller to set
        compatible flags.
        """
        raw_phase = str(getattr(config, "phase", "") or "").strip().lower()
        research_run = bool(getattr(config, "research_run", False))
        phase = ""
        phase_contract_error = ""
        if raw_phase:
            if raw_phase not in VALID_PHASES and raw_phase not in PHASE_ALIASES:
                if not research_run:
                    return problem, config
                phase_contract_error = f"unrecognized_research_phase:{raw_phase}"
            else:
                phase = normalize_phase(raw_phase)
        elif not research_run:
            return problem, config

        if not phase and bool(getattr(config, "thesis_mode", False)):
            phase = "phase3_two_stage"

        is_diagnostic = phase == "diagnostic"
        is_two_stage = phase == "phase3_two_stage"
        config = replace(
            config,
            phase=phase,
            resolved_phase=phase,
            executed_phase=phase,
            thesis_mode=bool(getattr(config, "thesis_mode", False) or is_two_stage),
            debug_mode=bool(getattr(config, "debug_mode", False) or is_diagnostic),
            diagnostic_mode=bool(getattr(config, "diagnostic_mode", False) or is_diagnostic),
            # A research candidate must be the solver decision trace itself.
            allow_postsolve_repair=False if research_run or phase else bool(
                getattr(config, "allow_postsolve_repair", True)
            ),
        )
        metadata = dict(problem.metadata or {})
        metadata.update(
            {
                "phase": phase or str(metadata.get("phase") or ""),
                "requested_phase_token": str(
                    getattr(config, "requested_phase_token", "")
                    or raw_phase
                    or ""
                ),
                "requested_phase": str(getattr(config, "requested_phase", "") or phase or ""),
                "resolved_phase": phase,
                "executed_phase": phase,
                "thesis_mode": bool(getattr(config, "thesis_mode", False)),
                "debug_mode": bool(getattr(config, "debug_mode", False)),
                "research_run": research_run,
                "postsolve_repair_allowed": bool(getattr(config, "allow_postsolve_repair", True)),
            }
        )
        if phase_contract_error:
            metadata["research_phase_contract_error"] = phase_contract_error
        if research_run:
            # This is a policy reward, not an operating cost.  It must never
            # influence an experimental run that is described as cost-based.
            # The integrated MILP reads this weight directly, so clearing it
            # here protects direct engine callers as well as the BFF path.
            problem = replace(
                problem,
                objective_weights=replace(
                    problem.objective_weights,
                    return_leg_bonus=0.0,
                ),
            )
            metadata.update(
                {
                    "research_objective_contract": "accounting_cost_terms_only",
                    "return_leg_bonus_disabled_for_research": True,
                    # A research run may not inherit a user-selected
                    # penalized-coverage relaxation.  Coverage is a physical
                    # feasibility condition, not a term to trade for cost.
                    "service_coverage_mode": "strict",
                    "research_forced_strict_coverage": True,
                    # The present integrated MILP still has internal charging
                    # priorities/penalties whose equality to the accounting
                    # ledger has not been proven.  A research run must be
                    # conservative: it can establish feasibility conditions,
                    # but cannot publish a global-cost-optimality claim until
                    # that objective contract is implemented and audited.
                    "solver_objective_matches_accounting_total": False,
                    "objective_semantics": "research_feasibility_not_yet_verified_global_accounting_cost",
                }
            )
            problem = replace(
                problem,
                scenario=replace(problem.scenario, service_coverage_mode="strict"),
            )
        if is_two_stage:
            # A two-stage decomposition has two solver objectives.  Its
            # accounting total is a KPI, not a globally minimized scalar cost.
            metadata.update(
                {
                    "objective_actual_cost_mode": True,
                    "solver_objective_matches_accounting_total": False,
                    "objective_semantics": (
                        "two_stage_assignment_energy_proxy_then_fixed_charging_"
                        "not_global_total_cost"
                    ),
                }
            )
        return replace(problem, metadata=metadata), config

    def _strict_precheck_infeasible_result(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        precheck: StrictCoveragePrecheckResult,
    ) -> OptimizationEngineResult:
        mode = config.mode
        display_name, maturity, true_family = self._solver_identity(mode)
        if bool(getattr(config, "research_run", False)):
            plan = AssignmentPlan(
                served_trip_ids=(),
                unserved_trip_ids=tuple(sorted(problem.eligible_trip_ids())),
                metadata={"source": "strict_coverage_precheck", "research_run": True},
            )
        else:
            plan = problem.baseline_plan or AssignmentPlan(
                served_trip_ids=(),
                unserved_trip_ids=tuple(sorted(problem.eligible_trip_ids())),
                metadata={"source": "strict_coverage_precheck"},
            )
        profile = {
            "total_wall_clock_sec": 0.0,
            "first_feasible_sec": None,
            "incumbent_updates": 0,
            "evaluator_calls": 0,
            "avg_evaluator_sec": 0.0,
            "repair_calls": 0,
            "avg_repair_sec": 0.0,
            "exact_repair_calls": 0,
            "avg_exact_repair_sec": 0.0,
            "feasible_candidate_ratio": 0.0,
            "rejected_candidate_ratio": 0.0,
            "fallback_count": 0,
        }
        solver_metadata = {
            "true_solver_family": true_family,
            "independent_implementation": True,
            "delegates_to": "none",
            "solver_display_name": display_name,
            "solver_maturity": maturity,
            **solver_benchmark_eligibility(
                mode,
                solver_maturity=maturity,
                true_solver_family=true_family,
                solver_display_name=display_name,
            ),
            "candidate_generation_mode": "strict_coverage_precheck",
            "research_run": bool(getattr(config, "research_run", False)),
            "evaluation_mode": problem.scenario.objective_mode,
            "objective_mode": problem.scenario.objective_mode,
            "service_coverage_mode": problem.scenario.service_coverage_mode,
            "termination_reason": "strict_coverage_precheck_infeasible",
            "fallback_applied": False,
            "fallback_reason": "none",
            "supports_exact_milp": False,
            "has_feasible_incumbent": False,
            "incumbent_count": 0,
            "warm_start_applied": bool(problem.baseline_plan is not None),
            "warm_start_source": "baseline_plan" if problem.baseline_plan is not None else "none",
            "strict_coverage_precheck": precheck.to_metadata(),
            "available_vehicle_count_total": int(precheck.available_vehicle_count),
            "strict_coverage_relaxed_vehicle_lower_bound": int(
                precheck.relaxed_vehicle_lower_bound
            ),
            "search_profile": profile,
            "effective_limits": {
                "time_limit_sec": int(config.time_limit_sec),
                "mip_gap": float(config.mip_gap),
            },
            "objective_weights": {
                "electricity_cost": float(problem.objective_weights.energy),
                "fuel_cost": float(problem.objective_weights.fuel),
                "demand_charge_cost": float(problem.objective_weights.demand),
                "vehicle_fixed_cost": float(problem.objective_weights.vehicle),
                "vehicle_usage_cost": float(problem.objective_weights.vehicle_usage),
                "unserved_penalty": float(problem.objective_weights.unserved),
                "switch_cost": float(problem.objective_weights.switch),
                "deviation_cost": float(problem.objective_weights.deviation),
                "degradation": float(problem.objective_weights.degradation),
                "utilization": float(problem.objective_weights.utilization),
                "return_leg_bonus": float(problem.objective_weights.return_leg_bonus),
            },
        }
        return OptimizationEngineResult(
            mode=mode,
            solver_status="SOLVED_INFEASIBLE",
            objective_value=float("inf"),
            plan=plan,
            feasible=False,
            warnings=(
                "Strict coverage precheck proved this input infeasible before solver invocation.",
            ),
            infeasibility_reasons=(
                "strict coverage relaxed path-cover lower bound "
                f"requires at least {precheck.relaxed_vehicle_lower_bound} vehicles, "
                f"but only {precheck.available_vehicle_count} are available",
            ),
            cost_breakdown={"objective_value": float("inf"), "total_cost": float("inf")},
            solver_metadata=solver_metadata,
            incumbent_history=(),
        )

    @staticmethod
    def _solver_identity(mode: OptimizationMode) -> tuple[str, str, str]:
        if mode == OptimizationMode.MILP:
            return ("MILP", "core", "milp")
        if mode == OptimizationMode.ALNS:
            return ("ALNS", "core", "alns")
        if mode == OptimizationMode.GA:
            return ("GA prototype", "prototype", "ga")
        if mode == OptimizationMode.ABC:
            return ("ABC prototype", "prototype", "abc")
        return ("MILPSeededALNS", "prototype", "milp_seeded_alns")

    def _finalize_result(
        self,
        problem: CanonicalOptimizationProblem,
        result: OptimizationEngineResult,
        config: OptimizationConfig | None = None,
    ) -> OptimizationEngineResult:
        allow_postsolve_repair = True if config is None else bool(getattr(config, "allow_postsolve_repair", True))
        plan, assignment_rebuilt, charging_recomputed, soc_repaired, opportunistic_topup_applied = self._normalize_postsolve_plan(
            problem,
            result.plan,
            mode=result.mode,
            solver_metadata=dict(result.solver_metadata or {}),
            allow_postsolve_repair=allow_postsolve_repair,
        )
        report = self._feasibility.evaluate(problem, plan)
        breakdown = self._evaluator.evaluate(problem, plan)
        vehicle_ledger, daily_ledger = self._evaluator.build_plan_ledgers(problem, plan, breakdown)
        plan = replace(plan, vehicle_cost_ledger=vehicle_ledger, daily_cost_ledger=daily_ledger)
        costs = breakdown.to_dict()
        candidate_plan = plan
        candidate_report = report
        candidate_costs = costs

        solver_metadata = dict(result.solver_metadata or {})
        final_solver_status = result.solver_status
        plan_metadata = dict(plan.metadata or {})
        for key in ("requested_phase_token", "requested_phase", "resolved_phase", "executed_phase"):
            if key not in solver_metadata or not str(solver_metadata.get(key) or "").strip():
                if key == "executed_phase":
                    # Executed phase must come from the solver adapter branch;
                    # copying the requested config would hide routing bugs.
                    solver_metadata[key] = str(plan_metadata.get(key) or "")
                else:
                    solver_metadata[key] = str(
                        plan_metadata.get(key)
                        or getattr(config, key, "")
                        or problem.metadata.get(key, "")
                        or ""
                    )
        for key in (
            "phase",
            "diagnostic_mode",
            "charging_dispatch_evaluated",
            "soc_constraints_evaluated",
            "supports_assignment_milp",
            "binding_constraint_report",
            "fragment_temporal_occupancy_constraint_count",
            "fragment_pairwise_depot_reset_constraint_count",
            "overlap_clique_constraint_count",
            "stage1_single_path_redundancy_elimination_applied",
            "stage1_energy_envelope_constraint_count",
            "stage1_energy_envelope_semantics",
            "stage1_time_indexed_soc_relaxation_constraint_count",
            "stage1_time_indexed_soc_relaxation_enabled",
            "stage1_time_indexed_soc_relaxation_semantics",
            "stage1_energy_cost_proxy_configuration",
            "stage1_energy_cost_proxy_weather_input",
            "stage1_energy_cost_proxy_result",
            "stage1_redundant_arc_link_constraints_omitted",
        ):
            if key in plan_metadata:
                solver_metadata[key] = plan_metadata[key]
        if "result_class" in plan_metadata:
            solver_metadata["result_class"] = plan_metadata["result_class"]
        if "research_kpi_eligible" in plan_metadata:
            solver_metadata["research_kpi_eligible"] = bool(plan_metadata["research_kpi_eligible"])
        solver_metadata["backend_objective_value_raw"] = float(result.objective_value)
        solver_metadata["postsolve_repair_allowed"] = bool(allow_postsolve_repair)
        solver_metadata["postsolve_assignment_rebuilt"] = bool(assignment_rebuilt)
        solver_metadata["postsolve_charging_recomputed"] = bool(charging_recomputed)
        solver_metadata["postsolve_soc_repair_applied"] = bool(soc_repaired)
        solver_metadata["postsolve_opportunistic_topup_applied"] = bool(opportunistic_topup_applied)
        solver_metadata["postsolve_opportunistic_topup_added_slot_count"] = int(
            plan.metadata.get("opportunistic_topup_added_slot_count", 0) or 0
        )
        solver_metadata["postsolve_opportunistic_topup_added_kwh"] = float(
            plan.metadata.get("opportunistic_topup_added_kwh", 0.0) or 0.0
        )
        solver_metadata["postsolve_opportunistic_topup_unfilled_kwh"] = float(
            plan.metadata.get("opportunistic_topup_unfilled_kwh", 0.0) or 0.0
        )
        solver_metadata["postsolve_opportunistic_topup_unfilled_vehicle_day_ids"] = tuple(
            plan.metadata.get("opportunistic_topup_unfilled_vehicle_day_ids", ()) or ()
        )
        solver_metadata["bess_terminal_soc_repair_shifted_to_grid_kwh"] = float(
            plan.metadata.get("bess_terminal_soc_repair_shifted_to_grid_kwh", 0.0) or 0.0
        )
        solver_metadata["bess_terminal_soc_violation_kwh"] = float(
            plan.metadata.get("bess_terminal_soc_violation_kwh", 0.0) or 0.0
        )
        solver_metadata["bess_terminal_soc_deviation_kwh"] = float(
            plan.metadata.get("bess_terminal_soc_deviation_kwh", 0.0) or 0.0
        )
        solver_metadata["bess_terminal_soc_target_kwh_by_depot"] = dict(
            plan.metadata.get("bess_terminal_soc_target_kwh_by_depot", {}) or {}
        )
        solver_metadata["bess_terminal_soc_deviation_kwh_by_depot"] = dict(
            plan.metadata.get("bess_terminal_soc_deviation_kwh_by_depot", {}) or {}
        )
        solver_metadata["bev_terminal_soc_policy"] = str(
            plan.metadata.get("bev_terminal_soc_policy")
            or problem.metadata.get("bev_terminal_soc_policy")
            or "minimum_only"
        )
        solver_metadata["bev_terminal_soc_target_source"] = str(
            problem.metadata.get("bev_terminal_soc_target_source") or ""
        )
        solver_metadata["bess_terminal_soc_target_source"] = str(
            problem.metadata.get("bess_terminal_soc_target_source") or ""
        )
        for key in (
            "vehicle_initial_soc_kwh_by_vehicle",
            "vehicle_terminal_soc_kwh_by_vehicle",
            "vehicle_terminal_soc_target_kwh_by_vehicle",
            "vehicle_terminal_soc_drawdown_kwh_by_vehicle",
            "vehicle_terminal_soc_target_shortfall_kwh_by_vehicle",
            "vehicle_terminal_soc_target_surplus_kwh_by_vehicle",
        ):
            solver_metadata[key] = dict(plan.metadata.get(key, {}) or {})
        solver_metadata["bev_terminal_soc_total_drawdown_kwh"] = float(
            plan.metadata.get("bev_terminal_soc_total_drawdown_kwh", 0.0) or 0.0
        )
        solver_metadata["bev_terminal_soc_total_target_shortfall_kwh"] = float(
            plan.metadata.get(
                "bev_terminal_soc_total_target_shortfall_kwh",
                0.0,
            )
            or 0.0
        )
        solver_metadata["bev_terminal_soc_total_target_surplus_kwh"] = float(
            plan.metadata.get(
                "bev_terminal_soc_total_target_surplus_kwh",
                0.0,
            )
            or 0.0
        )
        solver_metadata["bev_terminal_soc_max_abs_target_deviation_kwh"] = float(
            plan.metadata.get(
                "bev_terminal_soc_max_abs_target_deviation_kwh",
                0.0,
            )
            or 0.0
        )
        solver_metadata["bev_terminal_soc_balance_satisfied"] = bool(
            plan.metadata.get("bev_terminal_soc_balance_satisfied", False)
        )
        for key in (
            "physical_charger_assignment_semantics",
            "physical_charger_assignment_variable_count",
            "physical_charger_power_variable_count",
            "implicit_home_depot_charger_compatibility_vehicle_ids",
            "vehicle_compatible_charger_ids",
        ):
            solver_metadata[key] = plan.metadata.get(key)
        solver_metadata["source_provenance_exact"] = bool(
            dict(plan.metadata or {}).get("source_provenance_exact", False)
        )
        solver_metadata["derived_source_split"] = bool(
            dict(plan.metadata or {}).get("derived_source_split", False)
        )
        solver_metadata["postsolve_feasible"] = bool(report.feasible)
        solver_metadata["validation_metrics"] = dict(getattr(report, "metrics", {}) or {})
        solver_metadata["assignment_validation_diagnostics"] = [
            dict(item) for item in tuple(getattr(report, "diagnostics", ()) or ())
        ]
        dispatch_trips = tuple(
            getattr(getattr(problem, "dispatch_context", None), "trips", ()) or ()
        )
        unknown_operator_count = sum(
            1
            for trip in dispatch_trips
            if str(getattr(trip, "operator_id", "") or "").strip().upper()
            in {"", "UNKNOWN_OPERATOR", "UNKNOWN"}
        )
        distinct_operator_ids = tuple(
            sorted(
                {
                    str(getattr(trip, "operator_id", "") or "").strip()
                    for trip in dispatch_trips
                    if str(getattr(trip, "operator_id", "") or "").strip()
                }
            )
        )
        solver_metadata["operator_id_unknown_count"] = int(unknown_operator_count)
        solver_metadata["operator_ids_observed"] = distinct_operator_ids
        solver_metadata["postsolve_objective_value"] = float(
            costs.get("objective_value", result.objective_value)
        )
        bess_repair_applied = (
            float(solver_metadata.get("bess_terminal_soc_repair_shifted_to_grid_kwh", 0.0) or 0.0) > 1.0e-9
            or float(plan.metadata.get("bess_soc_boundary_adjusted_kwh", 0.0) or 0.0) > 1.0e-9
        )
        postsolve_modified_solution = bool(
            assignment_rebuilt
            or charging_recomputed
            or soc_repaired
            or opportunistic_topup_applied
            or bess_repair_applied
        )
        solver_metadata["postsolve_modified_solution"] = postsolve_modified_solution

        warnings = list(result.warnings or ())
        warnings.extend(report.warnings)
        if assignment_rebuilt:
            warnings.append(
                "Post-solve vehicle fragment reassignment rebuilt depot-reset-compatible duties."
            )
        if charging_recomputed:
            warnings.append(
                "Post-solve charging schedule was recomputed after vehicle fragment reassignment."
            )
        if soc_repaired:
            warnings.append(
                "Post-solve SOC repair adjusted charging to restore battery feasibility."
            )
        if opportunistic_topup_applied:
            warnings.append(
                "Post-solve opportunistic top-up added depot waiting charge to available EVs."
            )

        if result.mode == OptimizationMode.MILP and problem.baseline_plan is not None and allow_postsolve_repair:
            exact_milp_trace_preserved = bool(
                solver_metadata.get("supports_exact_milp", False)
                and solver_metadata.get("source_provenance_exact", False)
                and candidate_report.feasible
            )
            if exact_milp_trace_preserved:
                solver_metadata["truthful_baseline_guardrail_skipped"] = True
                solver_metadata["truthful_baseline_guardrail_skip_reason"] = "exact_milp_decision_trace_preserved"
            else:
                (
                    plan,
                    report,
                    costs,
                    solver_metadata,
                    warnings,
                ) = self._apply_milp_truthful_baseline_guardrail(
                    problem=problem,
                    candidate_plan=candidate_plan,
                    candidate_report=candidate_report,
                    candidate_costs=candidate_costs,
                    solver_status=result.solver_status,
                    solver_metadata=solver_metadata,
                    warnings=warnings,
                )
                if bool(solver_metadata.get("truthful_baseline_guardrail_applied")):
                    final_solver_status = "baseline_fallback"
                    solver_metadata["fallback_applied"] = True
                    solver_metadata["fallback_reason"] = "truthful_baseline_guardrail"
                    profile = dict(solver_metadata.get("search_profile") or {})
                    profile["fallback_count"] = int(profile.get("fallback_count", 0) or 0) + 1
                    solver_metadata["search_profile"] = profile
        if postsolve_modified_solution and not bool(solver_metadata.get("fallback_applied", False)):
            final_solver_status = "repaired_heuristic"
            solver_metadata["supports_exact_milp"] = False
            solver_metadata["result_class"] = "repaired_heuristic"
            solver_metadata["research_kpi_eligible"] = False
            solver_metadata["termination_reason"] = "postsolve_repaired_heuristic"
        elif postsolve_modified_solution:
            solver_metadata["research_kpi_eligible"] = False

        if bool(getattr(config, "research_run", False)):
            phase = str(solver_metadata.get("phase") or getattr(config, "phase", "") or "")
            assignment_only = phase == "phase2_assignment_only"
            charging_only = phase == "phase1_charging_only"
            two_stage = phase == "phase3_two_stage" or bool(
                solver_metadata.get("supports_two_stage_milp", False)
            )
            acceptance_checks = {
                "recognized_research_phase": phase in {
                    "phase1_charging_only",
                    "phase2_assignment_only",
                    "phase3_two_stage",
                    "phase4_integrated",
                },
                "no_fallback": not bool(solver_metadata.get("fallback_applied", False)),
                "no_postsolve_modification": not bool(postsolve_modified_solution),
                "all_trips_served": len(plan.unserved_trip_ids) == 0,
                "postsolve_feasible": bool(report.feasible),
                "not_diagnostic_or_debug": not bool(
                    getattr(config, "debug_mode", False)
                    or getattr(config, "diagnostic_mode", False)
                    or phase == "diagnostic"
                ),
                "phase_routing_exact": bool(
                    str(solver_metadata.get("requested_phase_token") or "").strip()
                    and normalize_phase(
                        solver_metadata.get("requested_phase_token"),
                        default=phase,
                    ) == phase
                    and str(solver_metadata.get("requested_phase") or "") == phase
                    and str(solver_metadata.get("resolved_phase") or "") == phase
                    and str(solver_metadata.get("executed_phase") or "") == phase
                ),
                "operator_id_resolved": bool(
                    not dispatch_trips
                    or (
                        unknown_operator_count == 0
                        and len(distinct_operator_ids) == 1
                    )
                ),
            }
            if assignment_only:
                acceptance_checks["assignment_milp_evaluated"] = bool(
                    solver_metadata.get("supports_assignment_milp", False)
                )
            elif charging_only:
                acceptance_checks["charging_dispatch_evaluated"] = bool(
                    solver_metadata.get("charging_dispatch_evaluated", False)
                )
                acceptance_checks["soc_constraints_evaluated"] = bool(
                    solver_metadata.get("soc_constraints_evaluated", False)
                )
                acceptance_checks["exact_milp_backend"] = bool(
                    solver_metadata.get("supports_exact_milp", False)
                )
                acceptance_checks["source_provenance_exact"] = bool(
                    solver_metadata.get("source_provenance_exact", False)
                )
            elif two_stage:
                # Phase 3 is the thesis' feasibility/constraint experiment:
                # the two exact stages produce a validated decision trace, but
                # do not minimize a single global accounting-cost scalar.
                # Its Stage 2 SOC model does not yet model an implicit reset
                # between disconnected fragments, so such a result must never
                # pass the research acceptance gate.
                single_continuous_vehicle_duty = bool(
                    plan.max_fragments_observed() <= 1
                )
                acceptance_checks["single_continuous_vehicle_duty"] = (
                    single_continuous_vehicle_duty
                )
                solver_metadata["single_continuous_vehicle_duty"] = (
                    single_continuous_vehicle_duty
                )
                acceptance_checks["two_stage_milp_evaluated"] = bool(
                    solver_metadata.get("supports_two_stage_milp", False)
                )
                acceptance_checks["exact_milp_backend"] = bool(
                    solver_metadata.get("supports_exact_milp", False)
                )
                acceptance_checks["source_provenance_exact"] = bool(
                    solver_metadata.get("source_provenance_exact", False)
                )
            else:
                # Integrated Phase 4 is an exact formulation of the current
                # discrete feasibility model.  Its accounting-cost equivalence
                # is intentionally a separate, not-yet-verified contract.
                acceptance_checks["integrated_milp_evaluated"] = bool(
                    solver_metadata.get("supports_integrated_exact_milp", False)
                )
                acceptance_checks["exact_milp_backend"] = bool(
                    solver_metadata.get("supports_exact_milp", False)
                )
                acceptance_checks["source_provenance_exact"] = bool(
                    solver_metadata.get("source_provenance_exact", False)
                )
            failed_checks = tuple(
                name for name, passed in acceptance_checks.items() if not bool(passed)
            )
            accepted = not failed_checks
            solver_metadata["research_run"] = True
            solver_metadata["research_acceptance_checks"] = acceptance_checks
            solver_metadata["research_run_accepted"] = accepted
            solver_metadata["research_feasibility_eligible"] = accepted
            research_cost_optimality_eligible = bool(
                accepted
                and phase == "phase4_integrated"
                and not assignment_only
                and not charging_only
                and not two_stage
                and bool(
                    solver_metadata.get("solver_objective_matches_accounting_total", False)
                )
                and bool(costs.get("objective_is_actual_cost", False))
            )
            terminal_policy = str(
                solver_metadata.get("bev_terminal_soc_policy")
                or (problem.metadata or {}).get("bev_terminal_soc_policy")
                or "minimum_only"
            ).strip().lower()
            cost_acceptance_checks = {
                "research_run_accepted": accepted,
                "full_operational_validation": not assignment_only,
                "source_provenance_exact": bool(
                    solver_metadata.get("source_provenance_exact", False)
                ),
                "bev_terminal_policy_return_to_initial": (
                    terminal_policy == "return_to_initial"
                ),
                "bev_terminal_soc_balance_satisfied": bool(
                    solver_metadata.get("bev_terminal_soc_balance_satisfied", False)
                ),
                "ev_energy_inventory_balanced": bool(
                    costs.get("ev_energy_inventory_balanced", False)
                ),
            }
            calendar_validation = dict(
                (problem.metadata or {}).get("service_calendar_validation") or {}
            )
            if calendar_validation:
                acceptance_checks["service_calendar_contract"] = (
                    str(calendar_validation.get("status") or "").upper() == "OK"
                )
            fleet_validation = dict(
                (problem.metadata or {}).get("research_fleet_validation") or {}
            )
            if str(fleet_validation.get("status") or "").upper() != "UNDECLARED":
                acceptance_checks["research_vehicle_inventory_contract"] = (
                    str(fleet_validation.get("status") or "").upper() == "OK"
                )
            research_accounting_cost_eligible = bool(
                all(cost_acceptance_checks.values())
                and not assignment_only
                and not charging_only
            )
            solver_metadata["research_cost_acceptance_checks"] = (
                cost_acceptance_checks
            )
            solver_metadata["research_accounting_cost_eligible"] = (
                research_accounting_cost_eligible
            )
            solver_metadata["research_cost_optimality_eligible"] = (
                research_cost_optimality_eligible
            )
            # A validated accounting cost for a feasible two-stage schedule is
            # publishable even though the schedule is not a global
            # total-cost optimum. Keep those two claims separate.
            solver_metadata["research_cost_kpi_eligible"] = bool(
                research_accounting_cost_eligible
                or research_cost_optimality_eligible
            )
            # Backward-compatible field: it has always been consumed by the
            # BFF as the permission to publish aggregate research KPIs.
            solver_metadata["research_kpi_eligible"] = bool(
                solver_metadata["research_cost_kpi_eligible"]
            )
            if not accepted:
                warnings.append(
                    "Research-run acceptance failed: " + ", ".join(failed_checks)
                )
                status = str(final_solver_status or "").strip().lower()
                has_feasible_incumbent = bool(
                    solver_metadata.get("has_feasible_incumbent", False)
                ) and bool(report.feasible)
                if status in {"infeasible", "solved_infeasible", "inf_or_unbd"}:
                    final_solver_status = "INFEASIBLE"
                    solver_metadata["result_class"] = "research_invalid"
                    solver_metadata["termination_reason"] = (
                        "research_acceptance_failed"
                    )
                elif not has_feasible_incumbent:
                    if status in {"time_limit", "suboptimal"}:
                        final_solver_status = "TIME_LIMIT_WITHOUT_VALID_SOLUTION"
                    else:
                        final_solver_status = "NO_VALID_INCUMBENT"
                    solver_metadata["result_class"] = "research_invalid"
                    solver_metadata["termination_reason"] = (
                        "research_acceptance_failed"
                    )
                else:
                    # A failed research gate (for example, a successor-pruned
                    # candidate network) invalidates exactness/KPI claims, not
                    # the existence of an independently validated incumbent.
                    solver_metadata["result_class"] = (
                        "feasible_research_ineligible"
                    )
                    solver_metadata["termination_reason"] = (
                        "feasible_incumbent_research_acceptance_failed"
                    )
            elif not bool(solver_metadata["research_cost_kpi_eligible"]):
                if charging_only and all(cost_acceptance_checks.values()):
                    warnings.append(
                        "Research fixed-assignment charging run accepted; its "
                        "accounting trace is balanced, but global assignment "
                        "and total-cost optimality are not established by Phase 1."
                    )
                else:
                    warnings.append(
                        "Research run accepted for feasibility/constraint analysis; "
                        "its cost KPI is not comparable because terminal energy "
                        "inventory or realized-flow accounting is incomplete."
                    )
            elif not bool(research_cost_optimality_eligible):
                warnings.append(
                    "Research accounting cost is valid for this feasible "
                    "schedule; global total-cost optimality is not established."
                )
        warnings = tuple(dict.fromkeys(str(item) for item in warnings if str(item).strip()))

        return replace(
            result,
            solver_status=final_solver_status,
            objective_value=float(costs.get("objective_value", result.objective_value)),
            plan=plan,
            feasible=report.feasible,
            warnings=warnings,
            infeasibility_reasons=report.errors,
            cost_breakdown=costs,
            solver_metadata=solver_metadata,
        )

    def _normalize_postsolve_plan(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
        *,
        mode: OptimizationMode | None = None,
        solver_metadata: dict | None = None,
        allow_postsolve_repair: bool = True,
    ) -> tuple[AssignmentPlan, bool, bool, bool, bool]:
        existing_source_flow_context = dict(getattr(plan, "metadata", {}) or {}).get("canonical_source_flow_context")
        if isinstance(existing_source_flow_context, dict) and existing_source_flow_context:
            source_flow_context = dict(existing_source_flow_context)
        else:
            source_flow_context = _capture_source_flow_context(plan)

        metadata = dict(getattr(plan, "metadata", {}) or {})
        if not allow_postsolve_repair:
            exact_context = {
                **source_flow_context,
                "source_provenance_exact": bool(metadata.get("source_provenance_exact", False)),
                "vehicle_source_provenance_exact": bool(metadata.get("vehicle_source_provenance_exact", False)),
                "derived_source_split": bool(metadata.get("derived_source_split", False)),
                "source_provenance_note": "Postsolve repair disabled; solver decision trace preserved for validation/reporting only.",
                "charging_slot_signatures": tuple(
                    _charging_slot_signature(slot) for slot in list(getattr(plan, "charging_slots", ()) or ())
                ),
            }
            return (
                replace(
                    plan,
                    metadata={
                        **metadata,
                        "postsolve_repair_allowed": False,
                        "canonical_source_flow_context": exact_context,
                    },
                ),
                False,
                False,
                False,
                False,
            )
        exact_milp_trace = (
            mode == OptimizationMode.MILP
            and bool((solver_metadata or {}).get("supports_exact_milp", False))
            and str(metadata.get("source") or "").strip() == "milp_gurobi"
            and _source_flow_context_has_positive_flow(source_flow_context)
        )
        if exact_milp_trace:
            pre_postsolve_report = self._feasibility.evaluate(problem, plan)
            if pre_postsolve_report.feasible:
                exact_context = {
                    **source_flow_context,
                    "source_provenance_exact": True,
                    "vehicle_source_provenance_exact": bool(metadata.get("vehicle_source_provenance_exact", False)),
                    "derived_source_split": False,
                    "source_provenance_note": "Exact MILP depot/slot energy-flow decision trace preserved without postsolve charging regeneration.",
                    "charging_slot_signatures": tuple(
                        _charging_slot_signature(slot) for slot in list(getattr(plan, "charging_slots", ()) or ())
                    ),
                }
                return (
                    replace(
                        plan,
                        metadata={
                            **metadata,
                            "source_provenance_exact": True,
                            "vehicle_source_provenance_exact": bool(metadata.get("vehicle_source_provenance_exact", False)),
                            "derived_source_split": False,
                            "canonical_source_flow_context": exact_context,
                        },
                    ),
                    False,
                    False,
                    False,
                    False,
                )

        rebuilt_plan = self._reassign_vehicle_fragments(problem, plan)
        assignment_rebuilt = rebuilt_plan != plan
        charging_recomputed = False
        soc_repaired = False

        if rebuilt_plan.duties:
            from src.optimization.alns.operators_repair import _with_recomputed_charging, soc_repair

            recomputed_plan = _with_recomputed_charging(problem, rebuilt_plan)
            charging_recomputed = recomputed_plan != rebuilt_plan
            rebuilt_plan = recomputed_plan
            repaired_plan = soc_repair(problem, rebuilt_plan)
            soc_repaired = repaired_plan != rebuilt_plan
            rebuilt_plan = repaired_plan

        topped_up_plan = apply_opportunistic_topup(problem, rebuilt_plan)
        opportunistic_topup_applied = int(topped_up_plan.metadata.get("opportunistic_topup_added_slot_count", 0) or 0) > 0
        if _source_flow_context_has_positive_flow(source_flow_context):
            topped_up_plan = _merge_source_context_with_added_charging(
                problem,
                topped_up_plan,
                source_flow_context,
            )
        else:
            topped_up_plan = _derive_depot_energy_source_split(problem, topped_up_plan)

        return (
            topped_up_plan,
            assignment_rebuilt,
            charging_recomputed,
            soc_repaired,
            opportunistic_topup_applied,
        )

    def _apply_milp_truthful_baseline_guardrail(
        self,
        *,
        problem: CanonicalOptimizationProblem,
        candidate_plan: AssignmentPlan,
        candidate_report,
        candidate_costs: dict,
        solver_status: str,
        solver_metadata: dict,
        warnings: list[str],
    ) -> tuple[AssignmentPlan, object, dict, dict, list[str]]:
        baseline_plan, baseline_assignment_rebuilt, baseline_charge_recomputed, baseline_soc_repaired, _baseline_topup_applied = (
            self._normalize_postsolve_plan(problem, problem.baseline_plan or AssignmentPlan())
        )
        baseline_report = self._feasibility.evaluate(problem, baseline_plan)
        baseline_breakdown = self._evaluator.evaluate(problem, baseline_plan)
        baseline_vehicle_ledger, baseline_daily_ledger = self._evaluator.build_plan_ledgers(
            problem,
            baseline_plan,
            baseline_breakdown,
        )
        baseline_plan = replace(
            baseline_plan,
            vehicle_cost_ledger=baseline_vehicle_ledger,
            daily_cost_ledger=baseline_daily_ledger,
        )
        baseline_costs = baseline_breakdown.to_dict()

        candidate_served = len(candidate_plan.served_trip_ids)
        baseline_served = len(baseline_plan.served_trip_ids)
        baseline_better = baseline_report.feasible and (
            baseline_served > candidate_served
            or (
                baseline_served == candidate_served
                and float(baseline_costs.get("objective_value", float("inf")))
                + 1.0e-6
                < float(candidate_costs.get("objective_value", float("inf")))
            )
        )
        if not baseline_better:
            return candidate_plan, candidate_report, candidate_costs, solver_metadata, warnings

        solver_metadata["milp_candidate_solver_status"] = str(solver_status or "")
        solver_metadata["milp_candidate_supports_exact_milp"] = bool(
            solver_metadata.get("supports_exact_milp", False)
        )
        solver_metadata["milp_candidate_trip_count_served"] = int(candidate_served)
        solver_metadata["milp_candidate_trip_count_unserved"] = int(len(candidate_plan.unserved_trip_ids))
        solver_metadata["milp_candidate_postsolve_objective_value"] = float(
            candidate_costs.get("objective_value", 0.0)
        )
        solver_metadata["truthful_baseline_guardrail_applied"] = True
        solver_metadata["truthful_baseline_trip_count_served"] = int(baseline_served)
        solver_metadata["truthful_baseline_trip_count_unserved"] = int(len(baseline_plan.unserved_trip_ids))
        solver_metadata["truthful_baseline_objective_value"] = float(
            baseline_costs.get("objective_value", 0.0)
        )
        solver_metadata["truthful_baseline_postsolve_assignment_rebuilt"] = bool(
            baseline_assignment_rebuilt
        )
        solver_metadata["truthful_baseline_postsolve_charging_recomputed"] = bool(
            baseline_charge_recomputed
        )
        solver_metadata["truthful_baseline_postsolve_soc_repair_applied"] = bool(
            baseline_soc_repaired
        )
        solver_metadata["supports_exact_milp"] = False
        solver_metadata["termination_reason"] = "truthful_baseline_guardrail"
        warnings = [
            item
            for item in warnings
            if "Uncovered trips:" not in str(item)
        ]
        warnings.append(
            "Truthful repaired baseline replaced a weaker MILP candidate after post-solve validation."
        )
        if baseline_assignment_rebuilt:
            warnings.append(
                "Truthful baseline guardrail rebuilt vehicle fragments before final export."
            )
        if baseline_charge_recomputed:
            warnings.append(
                "Truthful baseline guardrail recomputed charging before final export."
            )
        if baseline_soc_repaired:
            warnings.append(
                "Truthful baseline guardrail applied SOC repair before final export."
            )
        return baseline_plan, baseline_report, baseline_costs, solver_metadata, warnings

    def _reassign_vehicle_fragments(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> AssignmentPlan:
        if not plan.duties:
            return plan

        from src.dispatch.route_band import duty_route_band_ids, fragment_transition_is_feasible

        fixed_route_band_mode = bool(problem.metadata.get("fixed_route_band_mode", False))
        allow_same_day_depot_cycles = bool(
            problem.metadata.get(
                "allow_same_day_depot_cycles",
                getattr(problem.scenario, "allow_same_day_depot_cycles", True),
            )
        )
        max_fragments_per_vehicle_per_day = max(
            int(
                problem.metadata.get(
                    "daily_fragment_limit",
                    problem.metadata.get(
                        "max_depot_cycles_per_vehicle_per_day",
                        getattr(problem.scenario, "max_depot_cycles_per_vehicle_per_day", 1),
                    ),
                )
                or 1
            ),
            1,
        )
        horizon_start_min = int(problem.metadata.get("horizon_start_min") or 0)
        if horizon_start_min <= 0 and getattr(problem.scenario, "horizon_start", None):
            try:
                hh_text, mm_text = str(problem.scenario.horizon_start).split(":", 1)
                horizon_start_min = int(hh_text) * 60 + int(mm_text)
            except ValueError:
                horizon_start_min = 0
        max_fragments_per_vehicle = max(
            int(problem.metadata.get("max_start_fragments_per_vehicle") or 1),
            int(problem.metadata.get("max_end_fragments_per_vehicle") or 1),
            1,
        )
        vehicle_by_id = {
            str(vehicle.vehicle_id): vehicle
            for vehicle in problem.vehicles
        }
        kept_duties = []
        kept_map: dict[str, str] = {}
        duties_to_reassign = []

        for vehicle_id, duties in plan.duties_by_vehicle().items():
            vehicle = vehicle_by_id.get(str(vehicle_id))
            if vehicle is None:
                duties_to_reassign.extend(duty for duty in duties if duty.legs)
                continue
            if not bool(getattr(vehicle, "available", True)):
                duties_to_reassign.extend(duty for duty in duties if duty.legs)
                continue
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
            previous_kept = None
            for duty in duties:
                if not duty.legs:
                    continue
                if fixed_route_band_mode and len(duty_route_band_ids(duty)) > 1:
                    duties_to_reassign.append(duty)
                    continue
                if previous_kept is None:
                    kept_duties.append(duty)
                    kept_map[str(duty.duty_id)] = str(vehicle_id)
                    previous_kept = duty
                    continue
                if self._duties_overlap_in_time(
                    previous_kept,
                    duty,
                    horizon_start_min=horizon_start_min,
                ):
                    duties_to_reassign.append(duty)
                    continue
                if fragment_transition_is_feasible(
                    previous_kept,
                    duty,
                    home_depot_id=home_depot_id,
                    dispatch_context=problem.dispatch_context,
                    fixed_route_band_mode=fixed_route_band_mode,
                    allow_same_day_depot_cycles=allow_same_day_depot_cycles,
                ):
                    kept_duties.append(duty)
                    kept_map[str(duty.duty_id)] = str(vehicle_id)
                    previous_kept = duty
                    continue
                duties_to_reassign.append(duty)

        rebuilt_duties, duty_vehicle_map, skipped_trip_ids = assign_duty_fragments_to_vehicles(
            tuple(duties_to_reassign),
            vehicles=problem.vehicles,
            max_fragments_per_vehicle=max_fragments_per_vehicle,
            max_fragments_per_vehicle_per_day=max_fragments_per_vehicle_per_day,
            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            horizon_start_min=horizon_start_min,
            existing_duties=tuple(kept_duties),
            existing_duty_vehicle_map=kept_map,
            dispatch_context=problem.dispatch_context,
            fixed_route_band_mode=fixed_route_band_mode,
        )
        rebuilt_duties, duty_vehicle_map = self._merge_directly_connectable_fragments(
            problem,
            rebuilt_duties,
            duty_vehicle_map,
        )
        served_trip_ids = tuple(sorted({trip_id for duty in rebuilt_duties for trip_id in duty.trip_ids}))
        unserved_trip_ids = tuple(
            sorted((set(problem.eligible_trip_ids()) - set(served_trip_ids)).union(set(skipped_trip_ids)))
        )
        metadata = dict(plan.metadata or {})
        metadata["duty_vehicle_map"] = dict(duty_vehicle_map)
        metadata["postsolve_vehicle_fragment_reassignment"] = True
        return replace(
            plan,
            duties=rebuilt_duties,
            served_trip_ids=served_trip_ids,
            unserved_trip_ids=unserved_trip_ids,
            metadata=metadata,
        )

    @staticmethod
    def _duties_overlap_in_time(
        duty_a,
        duty_b,
        *,
        horizon_start_min: int = 0,
    ) -> bool:
        if not duty_a.legs or not duty_b.legs:
            return False
        duty_a_start = service_minute(
            duty_a.legs[0].trip.departure_min,
            horizon_start_min=horizon_start_min,
        )
        duty_a_end = service_minute(
            duty_a.legs[-1].trip.arrival_min,
            horizon_start_min=horizon_start_min,
        )
        duty_b_start = service_minute(
            duty_b.legs[0].trip.departure_min,
            horizon_start_min=horizon_start_min,
        )
        duty_b_end = service_minute(
            duty_b.legs[-1].trip.arrival_min,
            horizon_start_min=horizon_start_min,
        )
        if duty_a_end < duty_a_start:
            duty_a_end += 24 * 60
        if duty_b_end < duty_b_start:
            duty_b_end += 24 * 60
        return duty_a_start < duty_b_end and duty_b_start < duty_a_end

    def _merge_directly_connectable_fragments(
        self,
        problem: CanonicalOptimizationProblem,
        duties: tuple,
        duty_vehicle_map: dict[str, str],
    ) -> tuple[tuple, dict[str, str]]:
        from src.dispatch.route_band import (
            duty_route_band_ids,
            fragment_transition_allows_direct_connection,
            fragment_transition_direct_deadhead_min,
        )

        fixed_route_band_mode = bool(problem.metadata.get("fixed_route_band_mode", False))
        grouped: dict[str, list] = {}
        for duty in duties:
            vehicle_id = str(duty_vehicle_map.get(str(duty.duty_id)) or "")
            if vehicle_id:
                grouped.setdefault(vehicle_id, []).append(duty)

        merged_duties = []
        merged_map: dict[str, str] = {}
        for vehicle_id, vehicle_duties in grouped.items():
            ordered = sorted(
                vehicle_duties,
                key=lambda item: (
                    item.legs[0].trip.departure_min if item.legs else 10**9,
                    item.legs[-1].trip.arrival_min if item.legs else 10**9,
                    item.duty_id,
                ),
            )
            current = None
            fragment_index = 0
            for duty in ordered:
                if current is None:
                    current = duty
                    continue
                current_bands = duty_route_band_ids(current)
                next_bands = duty_route_band_ids(duty)
                band_mismatch = bool(
                    fixed_route_band_mode and current_bands and next_bands and current_bands != next_bands
                )
                can_direct = fragment_transition_allows_direct_connection(
                    current,
                    duty,
                    dispatch_context=problem.dispatch_context,
                )
                if can_direct and not band_mismatch and duty.legs:
                    direct_exists, direct_deadhead = fragment_transition_direct_deadhead_min(
                        current,
                        duty,
                        dispatch_context=problem.dispatch_context,
                    )
                    if direct_exists:
                        first_leg = replace(duty.legs[0], deadhead_from_prev_min=max(int(direct_deadhead), 0))
                        current = replace(
                            current,
                            legs=(
                                *current.legs,
                                first_leg,
                                *duty.legs[1:],
                            ),
                        )
                        continue
                fragment_index += 1
                duty_id = vehicle_id if fragment_index == 1 else f"{vehicle_id}__frag{fragment_index}"
                finalized = replace(current, duty_id=duty_id)
                merged_duties.append(finalized)
                merged_map[duty_id] = vehicle_id
                current = duty
            if current is not None:
                fragment_index += 1
                duty_id = vehicle_id if fragment_index == 1 else f"{vehicle_id}__frag{fragment_index}"
                finalized = replace(current, duty_id=duty_id)
                merged_duties.append(finalized)
                merged_map[duty_id] = vehicle_id

        return tuple(merged_duties), merged_map
