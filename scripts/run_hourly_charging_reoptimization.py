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
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Any


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
    _trip_input_hash,
    _vehicle_input_hash,
)


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


def _validate_day_ahead_input_contract(
    problem: Any,
    input_audit: dict[str, Any],
    *,
    scenario_id: str,
    prepared_input_id: str,
    service_date: str,
) -> None:
    """Ensure the persisted assignment was solved from the current inputs."""

    expected_values = {
        "scenario_id": str(scenario_id),
        "prepared_input_id": str(prepared_input_id),
        "service_date": str(service_date),
        "trip_input_hash": _trip_input_hash(problem),
        "vehicle_input_hash": _vehicle_input_hash(problem),
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


def run(args: argparse.Namespace) -> int:
    if not is_gurobi_available():
        raise RuntimeError(
            "Gurobi is unavailable; hourly research runs do not allow fallback"
        )

    prepared_root = _prepared_inputs_root()
    prepared_payload = load_prepared_input(
        scenario_id=args.scenario_id,
        prepared_input_id=args.prepared_input_id,
        scenarios_dir=prepared_root,
    )
    scenario = deepcopy(
        materialize_scenario_from_prepared_input(
            store.get_scenario_document_shallow(args.scenario_id),
            prepared_payload,
        )
    )
    scenario, weather_forecast, weather_profile = (
        _prepare_weather_policy_for_scenario(
            scenario,
            enable_weather_operation_policy=None,
            weather_proxy_forecast_path=None,
        )
    )
    enforce_research_phase3_single_continuous_duty(scenario)
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=int(args.time_limit_sec),
        stage2_time_limit_sec=int(args.time_limit_sec),
        mip_gap=float(args.mip_gap),
        random_seed=int(args.random_seed),
        research_run=True,
        allow_postsolve_repair=False,
        phase="phase1_charging_only",
        requested_phase="phase1_charging_only",
        resolved_phase="phase1_charging_only",
        executed_phase="phase1_charging_only",
    )
    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id=args.depot_id,
        service_id=args.service_id,
        config=config,
        planning_days=1,
    )
    if weather_forecast is not None and weather_profile is not None:
        problem = apply_weather_policy_to_problem(
            problem,
            weather_forecast,
            weather_profile,
            random_seed=int(args.random_seed),
        )
    service_date = str(problem.metadata.get("service_date") or "")[:10]
    if service_date != args.expected_service_date:
        raise ValueError(
            f"Service date mismatch: expected {args.expected_service_date}, got {service_date}"
        )

    terminal_floor_override = args.bess_terminal_min_kwh
    if terminal_floor_override is not None:
        assets = {
            str(depot_id): replace(
                asset,
                bess_terminal_soc_min_kwh=float(terminal_floor_override),
            )
            for depot_id, asset in dict(problem.depot_energy_assets or {}).items()
        }
        problem = replace(problem, depot_energy_assets=assets)

    day_ahead_result_path = Path(args.day_ahead_result).resolve()
    input_audit_path = day_ahead_result_path.parent / "input_audit.json"
    if not input_audit_path.is_file():
        raise ValueError(
            "The day-ahead result must have a sibling input_audit.json so its "
            "scenario, prepared input, and canonical hashes can be verified"
        )
    input_audit = _load_json(input_audit_path)
    _validate_day_ahead_input_contract(
        problem,
        input_audit,
        scenario_id=args.scenario_id,
        prepared_input_id=args.prepared_input_id,
        service_date=service_date,
    )
    day_ahead_payload = _load_json(day_ahead_result_path)
    day_ahead_plan = assignment_plan_from_serialized_result(
        problem,
        day_ahead_payload,
    )
    state = _load_json(Path(args.state_json)) if args.state_json else {}
    if int(args.execution_minutes) <= 0:
        raise ValueError("--execution-minutes must be positive")
    current_min = hhmm_to_min(args.current_time)
    state_current_min = state.get("current_min")
    if state_current_min is not None:
        absolute_state_min = int(state_current_min)
        if absolute_state_min % (24 * 60) != current_min % (24 * 60):
            raise ValueError(
                "state_json current_min does not match --current-time: "
                f"state={state_current_min}, current={current_min}"
            )
        current_min = absolute_state_min

    end_min = hhmm_to_min(args.end_time) if args.end_time else None
    while end_min is not None and end_min <= current_min:
        end_min += 24 * 60
    if end_min is not None and end_min <= current_min:
        raise ValueError("--end-time must be later than --current-time")
    if end_min is not None and (
        end_min - current_min
    ) % int(args.execution_minutes) != 0:
        raise ValueError(
            "The --current-time to --end-time interval must be divisible by "
            "--execution-minutes"
        )
    pv_forecast_updates = (
        _load_json(Path(args.pv_forecast_updates_json))
        if args.pv_forecast_updates_json
        else None
    )

    output_dir = Path(args.output_dir)
    rolling = RollingReoptimizer()
    summaries: list[dict[str, Any]] = []
    step_index = 0
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
            execution_minutes=int(args.execution_minutes),
            bess_terminal_policy=args.bess_terminal_policy,
        )
        elapsed = time.perf_counter() - started
        metadata = dict(result.solver_metadata or {})
        bess_end_by_depot = {
            str(depot_id): float(slot_map[max(slot_map)])
            for depot_id, slot_map in dict(
                result.plan.bess_soc_kwh_by_depot_slot or {}
            ).items()
            if slot_map
        }
        summary = {
            "scenario_id": args.scenario_id,
            "prepared_input_id": args.prepared_input_id,
            "service_date": service_date,
            "day_ahead_result": str(day_ahead_result_path),
            "day_ahead_input_audit": str(input_audit_path),
            "step_index": step_index,
            "current_time": current_label,
            "execution_minutes": int(args.execution_minutes),
            "lookahead": "remaining_service_day",
            "vehicle_assignment_policy": "fixed_to_persisted_day_ahead_result",
            "bess_terminal_policy": args.bess_terminal_policy,
            "bess_terminal_min_kwh_override": terminal_floor_override,
            "pv_forecast_update": pv_forecast_update_audit,
            "time_limit_sec": int(args.time_limit_sec),
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
            break

        next_min = current_min + int(args.execution_minutes)
        should_continue = end_min is not None and next_min < end_min
        if end_min is not None and not should_continue:
            summary["state_handoff"] = "not_required_at_chain_end"
        else:
            try:
                next_state = build_next_execution_state(
                    step_problem,
                    result,
                    current_min=current_min,
                    execution_minutes=int(args.execution_minutes),
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
                    raise

        _write_json(step_output_dir / "hourly_summary.json", summary)
        summaries.append(summary)
        if not should_continue:
            break
        current_min = next_min
        step_index += 1

    if end_min is not None:
        chain_summary = {
            "scenario_id": args.scenario_id,
            "prepared_input_id": args.prepared_input_id,
            "service_date": service_date,
            "current_time": args.current_time,
            "end_time": args.end_time,
            "execution_minutes": int(args.execution_minutes),
            "step_count": len(summaries),
            "all_steps_feasible": all(item["feasible"] for item in summaries),
            "objective_aggregation": "not_additive_remaining_horizon_objectives",
            "steps": summaries,
        }
        _write_json(output_dir / "rolling_chain_summary.json", chain_summary)
        print(
            json.dumps(chain_summary, ensure_ascii=False, indent=2, default=str),
            flush=True,
        )
    else:
        print(
            json.dumps(summaries[-1], ensure_ascii=False, indent=2, default=str),
            flush=True,
        )
    return 0 if summaries and all(item["feasible"] for item in summaries) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--prepared-input-id", required=True)
    parser.add_argument("--expected-service-date", required=True)
    parser.add_argument("--day-ahead-result", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--current-time", default="05:00")
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
    parser.add_argument("--depot-id", default="tsurumaki")
    parser.add_argument("--service-id", default="WEEKDAY")
    parser.add_argument("--state-json", default=None)
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
