from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.routers.optimization import _prepared_inputs_root
from bff.services.run_preparation import load_prepared_input, materialize_scenario_from_prepared_input
from bff.store import scenario_store as store
from src.optimization import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
    ResultSerializer,
)


FALLBACK_MILP_STATUSES = {
    "BASELINE_FALLBACK",
    "time_limit_baseline",
    "auto_relaxed_baseline",
    "gurobi_unavailable_baseline",
    "baseline_feasible",
}
# Standard 4-category result classification
RESULT_CATEGORIES = {
    "SOLVED_FEASIBLE",
    "SOLVED_INFEASIBLE",
    "NO_INCUMBENT",
    "BASELINE_FALLBACK",
}
MODE_MAP = {
    "milp": OptimizationMode.MILP,
    "alns": OptimizationMode.ALNS,
    "ga": OptimizationMode.GA,
    "abc": OptimizationMode.ABC,
}


def _pick_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _hhmm_to_bucket(hhmm_text: str) -> str:
    text = str(hhmm_text or "").strip()
    if len(text) < 2:
        return "unknown"
    return f"{text[:2]}:00-{text[:2]}:59"


def _load_fixed_scope(
    scenario_id: str,
    prepared_input_id: str,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    prepared_root = _prepared_inputs_root()
    prepared_payload = load_prepared_input(
        scenario_id=scenario_id,
        prepared_input_id=prepared_input_id,
        scenarios_dir=prepared_root,
    )
    prepared_path = prepared_root / scenario_id / f"{prepared_input_id}.json"
    scenario = materialize_scenario_from_prepared_input(
        store.get_scenario_document_shallow(scenario_id),
        prepared_payload,
    )
    return scenario, prepared_payload, prepared_path


def _validate_fixed_scope(
    scenario: dict[str, Any],
    prepared_payload: dict[str, Any],
    *,
    depot_id: str,
    service_id: str,
    objective_mode: str,
) -> None:
    scope = dict(prepared_payload.get("scope") or {})
    service_dates = tuple((scope.get("service_dates") or []))
    planning_days = int(scope.get("planning_days") or 0)
    depots = tuple(scope.get("depot_ids") or ())
    services = tuple(scope.get("service_ids") or ())
    scenario_objective = _pick_text(
        (scenario.get("simulation_config") or {}).get("objective_mode"),
        (scenario.get("scenario_overlay") or {}).get("objective_mode"),
    )

    if tuple(depots) != (depot_id,):
        raise ValueError(f"Prepared scope depot_ids={depots} does not match fixed depot_id={depot_id}")
    if tuple(services) != (service_id,):
        raise ValueError(f"Prepared scope service_ids={services} does not match fixed service_id={service_id}")
    if planning_days != 1:
        raise ValueError(f"Prepared scope planning_days={planning_days} is not fixed to 1")
    if len(service_dates) != 1:
        raise ValueError(f"Prepared scope service_dates={service_dates} is not fixed to a single day")
    if scenario_objective and scenario_objective != objective_mode:
        raise ValueError(
            f"Scenario objective_mode={scenario_objective} does not match fixed objective_mode={objective_mode}"
        )
    timetable_rows = scenario.get("timetable_rows") or ()
    trips = prepared_payload.get("trips") or ()
    if len(timetable_rows) != len(trips):
        raise ValueError(
            "materialized timetable_rows count does not match prepared trips; "
            "this harness requires prepared timetable_rows without regeneration"
        )


def _trip_meta_by_id(prepared_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for item in prepared_payload.get("trips") or ():
        if not isinstance(item, dict):
            continue
        trip_id = _pick_text(item.get("trip_id"))
        if not trip_id:
            continue
        allowed_types = tuple(
            str(vehicle_type or "").strip()
            for vehicle_type in (item.get("allowed_vehicle_types") or ())
            if str(vehicle_type or "").strip()
        )
        meta[trip_id] = {
            "route_family_code": _pick_text(item.get("routeFamilyCode"), item.get("routeCode"), item.get("route_id")) or "unknown",
            "route_family_label": _pick_text(item.get("routeFamilyLabel"), item.get("routeLabel")),
            "route_id": _pick_text(item.get("route_id")),
            "departure": _pick_text(item.get("departure")),
            "arrival": _pick_text(item.get("arrival")),
            "origin": _pick_text(item.get("origin")),
            "destination": _pick_text(item.get("destination")),
            "time_bucket": _hhmm_to_bucket(item.get("departure")),
            "allowed_vehicle_types": allowed_types,
            "is_shared_trip": len(set(allowed_types)) > 1,
        }
    return meta


def _plan_trip_vehicle_type_map(result_payload: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for duty in result_payload.get("duties") or ():
        if not isinstance(duty, dict):
            continue
        vehicle_type = _pick_text(duty.get("vehicle_type")) or "unknown"
        for trip_id in duty.get("trip_ids") or ():
            trip_key = _pick_text(trip_id)
            if trip_key:
                mapping[trip_key] = vehicle_type
    return mapping


def _count_by_counter(counter: Counter[str]) -> dict[str, int]:
    return {key: int(value) for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0]))}


def _used_vehicle_type_counts(
    result_payload: dict[str, Any],
    vehicle_type_by_id: dict[str, str],
) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for vehicle_id, trip_ids in (result_payload.get("vehicle_paths") or {}).items():
        if not trip_ids:
            continue
        counter[_pick_text(vehicle_type_by_id.get(str(vehicle_id)), "unknown")] += 1
    return _count_by_counter(counter)


def _shared_trip_assignment_summary(
    trip_meta_by_id: dict[str, dict[str, Any]],
    served_trip_vehicle_type: dict[str, str],
    *,
    families: Iterable[str] = (),
) -> dict[str, int]:
    family_filter = {family for family in families if family}
    counter: Counter[str] = Counter()
    for trip_id, vehicle_type in served_trip_vehicle_type.items():
        meta = trip_meta_by_id.get(trip_id)
        if not meta or not meta.get("is_shared_trip"):
            continue
        family_code = str(meta.get("route_family_code") or "")
        if family_filter and family_code not in family_filter:
            continue
        counter[str(vehicle_type or "unknown")] += 1
    return _count_by_counter(counter)


def _served_trip_assignment_summary(
    trip_meta_by_id: dict[str, dict[str, Any]],
    served_trip_vehicle_type: dict[str, str],
    *,
    families: Iterable[str] = (),
) -> dict[str, int]:
    family_filter = {family for family in families if family}
    counter: Counter[str] = Counter()
    for trip_id, vehicle_type in served_trip_vehicle_type.items():
        meta = trip_meta_by_id.get(trip_id)
        if not meta:
            continue
        family_code = str(meta.get("route_family_code") or "")
        if family_filter and family_code not in family_filter:
            continue
        counter[str(vehicle_type or "unknown")] += 1
    return _count_by_counter(counter)


def _unserved_breakdown(
    trip_meta_by_id: dict[str, dict[str, Any]],
    unserved_trip_ids: Iterable[str],
) -> dict[str, Any]:
    family_counter: Counter[str] = Counter()
    bucket_counter: Counter[str] = Counter()
    shared_family_counter: Counter[str] = Counter()
    route24_23_samples: list[dict[str, Any]] = []

    for trip_id in unserved_trip_ids:
        meta = trip_meta_by_id.get(trip_id, {})
        family_code = _pick_text(meta.get("route_family_code")) or "unknown"
        time_bucket = _pick_text(meta.get("time_bucket")) or "unknown"
        family_counter[family_code] += 1
        bucket_counter[time_bucket] += 1
        if meta.get("is_shared_trip"):
            shared_family_counter[family_code] += 1
        if family_code in {"渋24", "渋23"} and len(route24_23_samples) < 12:
            route24_23_samples.append(
                {
                    "trip_id": trip_id,
                    "route_family_code": family_code,
                    "departure": _pick_text(meta.get("departure")),
                    "arrival": _pick_text(meta.get("arrival")),
                    "origin": _pick_text(meta.get("origin")),
                    "destination": _pick_text(meta.get("destination")),
                }
            )

    return {
        "route_family_counts": _count_by_counter(family_counter),
        "time_bucket_counts": _count_by_counter(bucket_counter),
        "shared_trip_family_counts": _count_by_counter(shared_family_counter),
        "route24_route23_samples": route24_23_samples,
    }


def _milp_exactness_class(row: dict[str, Any]) -> str:
    if row["mode"] != "milp":
        return "metaheuristic"
    if row["solver_status"] in FALLBACK_MILP_STATUSES:
        return "fallback"
    if not bool(row.get("supports_exact_milp")):
        return "fallback"
    if row.get("plan_source") != "milp_gurobi":
        return "fallback"
    if row["solver_status"] == "optimal":
        return "exact_optimal"
    return "exact_incumbent"


def _mode_config(base: OptimizationConfig, mode_label: str) -> OptimizationConfig:
    return OptimizationConfig(
        mode=MODE_MAP[mode_label],
        time_limit_sec=int(base.time_limit_sec),
        mip_gap=float(base.mip_gap),
        random_seed=int(base.random_seed),
        alns_iterations=int(base.alns_iterations),
        no_improvement_limit=int(base.no_improvement_limit),
        destroy_fraction=float(base.destroy_fraction),
        partial_milp_trip_limit=int(base.partial_milp_trip_limit),
        rolling_current_min=base.rolling_current_min,
        target_gap_to_baseline=base.target_gap_to_baseline,
        warm_start=bool(base.warm_start),
        acceptance=str(base.acceptance),
        operator_selection=str(base.operator_selection),
        use_data_driven_peak_removal=bool(base.use_data_driven_peak_removal),
        peak_hour_windows_min=tuple(base.peak_hour_windows_min),
        worst_trip_scoring=str(base.worst_trip_scoring),
    )


def _write_csv(rows: Iterable[dict[str, Any]], csv_path: Path) -> None:
    fieldnames = [
        "mode",
        "solver_status",
        "result_category",
        "milp_exactness_class",
        "supports_exact_milp",
        "true_solver_family",
        "independent_implementation",
        "has_feasible_incumbent",
        "incumbent_count",
        "warm_start_applied",
        "warm_start_source",
        "termination_reason",
        "objective_value",
        "solve_time_seconds",
        "trip_count_served",
        "trip_count_unserved",
        "vehicle_count_used",
        "plan_source",
        "plan_status",
        "milp_status",
        "warnings_count",
        "incumbent_history_count",
        "unserved_route24",
        "unserved_route23",
        "per_solver_result_json",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def _build_row(
    *,
    mode_label: str,
    result_payload: dict[str, Any],
    result_json_path: Path,
    wall_clock_seconds: float,
    trip_meta_by_id: dict[str, dict[str, Any]],
    vehicle_type_by_id: dict[str, str],
) -> dict[str, Any]:
    unserved_trip_ids = tuple(sorted(str(trip_id) for trip_id in (result_payload.get("unserved_trip_ids") or ())))
    served_trip_ids = tuple(sorted(str(trip_id) for trip_id in (result_payload.get("served_trip_ids") or ())))
    solver_metadata = dict(result_payload.get("solver_metadata") or {})
    warnings = list(result_payload.get("warnings") or ())
    served_trip_vehicle_type = _plan_trip_vehicle_type_map(result_payload)
    unserved_breakdown = _unserved_breakdown(trip_meta_by_id, unserved_trip_ids)

    row = {
        "mode": mode_label,
        "solver_status": _pick_text(result_payload.get("solver_status"), result_payload.get("status")),
        "supports_exact_milp": bool(solver_metadata.get("supports_exact_milp")),
        "termination_reason": _pick_text(result_payload.get("termination_reason"), solver_metadata.get("termination_reason")),
        "objective_value": float(result_payload.get("objective_value") or 0.0),
        "solve_time_seconds": round(float(wall_clock_seconds), 6),
        "trip_count_served": len(served_trip_ids),
        "trip_count_unserved": len(unserved_trip_ids),
        "vehicle_count_used": sum(1 for trip_ids in (result_payload.get("vehicle_paths") or {}).values() if trip_ids),
        "plan_source": _pick_text((result_payload.get("metadata") or {}).get("source")),
        "plan_status": _pick_text((result_payload.get("metadata") or {}).get("status")),
        "milp_status": _pick_text((result_payload.get("metadata") or {}).get("milp_status")),
        # New 4-category result classification metadata
        "true_solver_family": _pick_text(solver_metadata.get("true_solver_family")),
        "independent_implementation": bool(solver_metadata.get("independent_implementation", True)),
        "has_feasible_incumbent": bool(solver_metadata.get("has_feasible_incumbent")),
        "incumbent_count": int(solver_metadata.get("incumbent_count", 0)),
        "warm_start_applied": bool(solver_metadata.get("warm_start_applied")),
        "warm_start_source": _pick_text(solver_metadata.get("warm_start_source")),
        "result_category": _pick_text(result_payload.get("solver_status")) if _pick_text(result_payload.get("solver_status")) in RESULT_CATEGORIES else "UNKNOWN",
        "effective_limits": dict(result_payload.get("effective_limits") or {}),
        "warnings": warnings,
        "warnings_count": len(warnings),
        "infeasibility_reasons": list(result_payload.get("infeasibility_reasons") or ()),
        "incumbent_history_count": len(result_payload.get("incumbent_history") or ()),
        "incumbent_history": list(result_payload.get("incumbent_history") or ()),
        "incumbent_history_tail": list((result_payload.get("incumbent_history") or ())[-5:]),
        "cost_breakdown": dict(result_payload.get("cost_breakdown") or {}),
        "per_solver_result_json": str(result_json_path),
        "unserved_route24": int(unserved_breakdown["route_family_counts"].get("渋24", 0)),
        "unserved_route23": int(unserved_breakdown["route_family_counts"].get("渋23", 0)),
        "unserved_route_family_counts": unserved_breakdown["route_family_counts"],
        "unserved_time_bucket_counts": unserved_breakdown["time_bucket_counts"],
        "unserved_shared_trip_family_counts": unserved_breakdown["shared_trip_family_counts"],
        "route24_route23_unserved_samples": unserved_breakdown["route24_route23_samples"],
        "used_vehicle_count_by_type": _used_vehicle_type_counts(result_payload, vehicle_type_by_id),
        "served_trip_count_by_vehicle_type": _served_trip_assignment_summary(trip_meta_by_id, served_trip_vehicle_type),
        "served_route24_route23_by_vehicle_type": _served_trip_assignment_summary(
            trip_meta_by_id,
            served_trip_vehicle_type,
            families=("渋24", "渋23"),
        ),
        "shared_trip_assignment_by_vehicle_type": _shared_trip_assignment_summary(
            trip_meta_by_id,
            served_trip_vehicle_type,
        ),
        "shared_route24_route23_assignment_by_vehicle_type": _shared_trip_assignment_summary(
            trip_meta_by_id,
            served_trip_vehicle_type,
            families=("渋24", "渋23"),
        ),
        "shared_trip_unserved_count": sum(
            1
            for trip_id in unserved_trip_ids
            if bool((trip_meta_by_id.get(trip_id) or {}).get("is_shared_trip"))
        ),
    }
    row["milp_exactness_class"] = _milp_exactness_class(row)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the fixed prepared scope comparison without regenerating timetable_rows."
    )
    parser.add_argument("--scenario-id", default="237d5623-aa94-4f72-9da1-17b9070264be")
    parser.add_argument("--prepared-input-id", default="prepared-11efb997690030ef")
    parser.add_argument("--depot-id", default="tsurumaki")
    parser.add_argument("--service-id", default="WEEKDAY")
    parser.add_argument("--objective-mode", default="total_cost")
    parser.add_argument("--time-limit-seconds", type=int, default=300)
    parser.add_argument("--mip-gap", type=float, default=0.05)  # Relaxed from 0.01 to 0.05 for faster solutions
    parser.add_argument("--alns-iterations", type=int, default=800)  # Increased from 500
    parser.add_argument("--no-improvement-limit", type=int, default=150)  # Increased from 120
    parser.add_argument("--destroy-fraction", type=float, default=0.25)
    parser.add_argument(
        "--output-stem",
        default="outputs/mode_compare_route24_fix_rerun_20260405",
        help="Base path without extension for comparison outputs",
    )
    args = parser.parse_args()

    scenario, prepared_payload, prepared_path = _load_fixed_scope(
        args.scenario_id,
        args.prepared_input_id,
    )
    _validate_fixed_scope(
        scenario,
        prepared_payload,
        depot_id=args.depot_id,
        service_id=args.service_id,
        objective_mode=args.objective_mode,
    )

    base_config = OptimizationConfig(
        time_limit_sec=args.time_limit_seconds,
        mip_gap=args.mip_gap,
        random_seed=42,
        alns_iterations=args.alns_iterations,
        no_improvement_limit=args.no_improvement_limit,
        destroy_fraction=args.destroy_fraction,
        warm_start=True,
    )
    planning_days = int(((scenario.get("simulation_config") or {}).get("planning_days") or 1))
    if planning_days != 1:
        raise ValueError(f"Scenario planning_days={planning_days} is not fixed to one day")

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id=args.depot_id,
        service_id=args.service_id,
        config=base_config,
        planning_days=planning_days,
    )
    trip_meta_by_id = _trip_meta_by_id(prepared_payload)
    vehicle_type_by_id = {
        str(vehicle.vehicle_id): str(vehicle.vehicle_type)
        for vehicle in problem.vehicles
    }
    output_stem = Path(args.output_stem)
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    result_dir = output_stem.parent / output_stem.name
    result_dir.mkdir(parents=True, exist_ok=True)

    engine = OptimizationEngine()
    rows: list[dict[str, Any]] = []
    mode_order = ("milp", "alns", "ga", "abc")
    for mode_label in mode_order:
        config = _mode_config(base_config, mode_label)
        started = time.perf_counter()
        result = engine.solve(problem, config)
        elapsed = time.perf_counter() - started
        payload = ResultSerializer.serialize_result(result)
        payload["comparison_context"] = {
            "scenario_id": args.scenario_id,
            "prepared_input_id": args.prepared_input_id,
            "depot_id": args.depot_id,
            "service_id": args.service_id,
            "objective_mode": args.objective_mode,
            "time_limit_seconds": args.time_limit_seconds,
            "mip_gap": args.mip_gap,
            "planning_days": planning_days,
            "prepared_input_path": str(prepared_path),
            "timetable_rows_regenerated": False,
            "wall_clock_seconds": round(float(elapsed), 6),
        }
        result_json_path = result_dir / f"{mode_label}.json"
        result_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        row = _build_row(
            mode_label=mode_label,
            result_payload=payload,
            result_json_path=result_json_path,
            wall_clock_seconds=elapsed,
            trip_meta_by_id=trip_meta_by_id,
            vehicle_type_by_id=vehicle_type_by_id,
        )
        rows.append(row)
        print(
            json.dumps(
                {
                    "mode": row["mode"],
                    "solver_status": row["solver_status"],
                    "milp_exactness_class": row["milp_exactness_class"],
                    "trip_count_served": row["trip_count_served"],
                    "trip_count_unserved": row["trip_count_unserved"],
                    "solve_time_seconds": row["solve_time_seconds"],
                },
                ensure_ascii=False,
            )
        )

    comparison = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario_id": args.scenario_id,
        "prepared_input_id": args.prepared_input_id,
        "prepared_input_path": str(prepared_path),
        "depot_id": args.depot_id,
        "service_id": args.service_id,
        "planning_days": planning_days,
        "objective_mode": args.objective_mode,
        "time_limit_seconds": args.time_limit_seconds,
        "mip_gap": args.mip_gap,
        "timetable_rows_regenerated": False,
        "rows": rows,
    }
    comparison_json_path = output_stem.with_suffix(".json")
    comparison_csv_path = output_stem.with_suffix(".csv")
    comparison_json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(rows, comparison_csv_path)

    verdict_lines = [
        "# Fixed Case Verdict",
        "",
        f"- scenario: `{args.scenario_id}`",
        f"- prepared_input: `{args.prepared_input_id}`",
        f"- depot/service: `{args.depot_id}` / `{args.service_id}`",
        f"- objective_mode: `{args.objective_mode}`",
        f"- timetable_rows_regenerated: `{False}`",
        "",
    ]
    all_zero_unserved = all(int(row["trip_count_unserved"]) == 0 for row in rows)
    milp_row = next(row for row in rows if row["mode"] == "milp")
    verdict_lines.append(f"- all_974_served: `{all_zero_unserved}`")
    verdict_lines.append(
        f"- milp_exactness: `{milp_row['milp_exactness_class']}` "
        f"(status=`{milp_row['solver_status']}`, supports_exact_milp=`{milp_row['supports_exact_milp']}`)"
    )
    if not all_zero_unserved:
        families = Counter()
        for row in rows:
            for family_code, count in dict(row.get("unserved_route_family_counts") or {}).items():
                families[family_code] += int(count)
        top_text = ", ".join(f"{family}:{count}" for family, count in families.most_common(8))
        verdict_lines.append(f"- next_shrink_target: `{top_text or 'route24 or route24+route23'}`")
    else:
        verdict_lines.append("- next_shrink_target: `not needed for current fixed case; if MILP exact化を続けるなら route24 単独 or route24+route23 strict MILP`")
    verdict_path = result_dir / "verdict.md"
    verdict_path.write_text("\n".join(verdict_lines) + "\n", encoding="utf-8")

    print(str(comparison_json_path))
    print(str(comparison_csv_path))
    print(str(verdict_path))


if __name__ == "__main__":
    main()
