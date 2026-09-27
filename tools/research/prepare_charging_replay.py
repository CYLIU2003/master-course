"""Reconstruct one saved charging window without starting a solver or a job.

The archive digest must come from the original collection receipt. This is an
input preflight for a later paired diagnostic, not a successful optimization.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.run_hourly_charging_reoptimization import (
    RollingChainRequest, rolling_solver_config, _canonical_hash,
    _apply_pv_forecast_update, _validate_day_ahead_input_contract,
)
from src.optimization import ProblemBuilder
from src.optimization.rolling.reoptimizer import (
    RollingReoptimizer, assignment_plan_from_serialized_result,
)
from src.solver_policy import NO_GUROBI_PROFILE, solver_policy_scope


def saved_window(summary: dict, state: dict, audit: dict) -> RollingChainRequest:
    current = summary.get("current_absolute_min")
    if type(current) is not int or state.get("current_min") != current:
        raise ValueError("Saved state does not start at the requested window")
    for key in ("scenario_id", "prepared_input_id", "service_date"):
        if not summary.get(key) or summary[key] != audit.get(key):
            raise ValueError(f"Saved window differs from input audit: {key}")
    if summary.get("pv_forecast_update") is not None:
        raise ValueError("Updated PV forecasts need their original saved update; unsupported here")
    if summary.get("bess_terminal_min_kwh_override") is not None:
        raise ValueError("BESS override replay is not supported")
    for key in ("execution_minutes", "time_limit_sec", "gurobi_threads", "random_seed", "lookahead"):
        value = summary.get(key)
        if type(value) is not int or value < (0 if key == "random_seed" else 1):
            raise ValueError(f"Missing or invalid saved control: {key}")
    gap = summary.get("mip_gap")
    if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or not 0 <= gap <= 1:
        raise ValueError("Missing or invalid saved control: mip_gap")
    # Only rolling_solver_config consumes this request. This preflight never
    # calls run_rolling_chain or uses the required path placeholders as files.
    return RollingChainRequest(
        scenario_id=summary["scenario_id"], prepared_input_id=summary["prepared_input_id"],
        expected_service_date=summary["service_date"], day_ahead_result_path="", output_dir="",
        current_time=summary["current_time"], execution_minutes=summary["execution_minutes"],
        time_limit_sec=summary["time_limit_sec"], mip_gap=summary["mip_gap"],
        random_seed=summary["random_seed"], gurobi_threads=summary["gurobi_threads"],
        service_id=audit["service_id"], lookahead_hours=summary["lookahead"],
        bess_terminal_policy=summary["bess_terminal_policy"], research_run=False,
    )


def capture_window(problem, plan, request, state):
    """Use the production state transformation and stop at the solver boundary."""
    rolling = RollingReoptimizer()
    rolling._engine = SimpleNamespace(solve=lambda problem, config: (problem, config))
    fields = {
        "actual_soc": "actual_vehicle_soc_kwh", "actual_bess_soc_kwh": "actual_bess_soc_kwh",
        "actual_vehicle_fuel_l": "actual_vehicle_fuel_l", "actual_vehicle_positions": "actual_vehicle_positions",
        "connected_charger_by_vehicle": "connected_charger_by_vehicle",
        "observed_on_peak_kw_by_depot": "observed_on_peak_kw_by_depot",
        "observed_off_peak_kw_by_depot": "observed_off_peak_kw_by_depot",
    }
    return rolling.reoptimize_charging_hour(
        problem, plan, rolling_solver_config(request), state["current_min"],
        **{target: dict(state.get(source) or {}) for target, source in fields.items()},
        active_charge_session_vehicle_ids=tuple(state.get("active_charge_session_vehicle_ids") or ()),
        execution_minutes=request.execution_minutes, bess_terminal_policy=request.bess_terminal_policy,
        lookahead_hours=request.lookahead_hours,
    )


def prepare(archive_path: Path, expected_sha: str, step: int):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("An original SHA256 receipt is required")
    if type(step) is not int or step < 1:
        raise ValueError("Choose a saved window after the first, with an explicit preceding state")
    with archive_path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != expected_sha:
            raise ValueError("Archive digest mismatch")
        # A receipt-bound archive digest covers every member, including the
        # assignment and executed state; no new per-result audit field is invented.
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate archive members")
            summaries = [n for n in names if re.search(rf"/step_{step:02d}_[^/]+/hourly_summary\.json$", n)]
            if len(summaries) != 1:
                raise ValueError("Expected exactly one saved window")
            prefix = summaries[0].split("rolling_hourly_chain/")[0]
            previous = [n for n in names if n.startswith(prefix) and re.search(
                rf"/step_{step-1:02d}_[^/]+/state_for_next_hour\.json$", n)]
            if len(previous) != 1:
                raise ValueError("Expected exactly one preceding execution state")
            evidence = {}
            def read(name):
                if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                    raise ValueError("Unsafe evidence member")
                content = archive.read(name)
                evidence[name] = hashlib.sha256(content).hexdigest()
                return json.loads(content)
            summary, state = read(summaries[0]), read(previous[0])
            audit = read(prefix + "input_audit.json")
            scenario = read(prefix + "effective_scenario.json")
            pv = read(prefix + "effective_pv_profiles.json")
            serialized = read(prefix + "canonical_solver_result.json")
            manifest = read("manifest.json")
        source.seek(0)
        if hashlib.file_digest(source, "sha256").hexdigest() != expected_sha:
            raise ValueError("Archive changed while reading inputs")
    if _canonical_hash(scenario) != audit["effective_scenario_sha256"]:
        raise ValueError("Effective scenario mismatch")
    if evidence[prefix + "effective_pv_profiles.json"] != audit["effective_pv_profiles_sha256"]:
        raise ValueError("Effective PV mismatch")
    if pv.get("schema_version") != "effective_pv_profiles_v1":
        raise ValueError("Unsupported effective PV schema")
    if manifest.get("git", {}).get("dirty") is not False or not manifest.get("git", {}).get("sha"):
        raise ValueError("Source archive must identify a clean frozen commit")
    if summary.get("step_index") != step:
        raise ValueError("Saved summary step differs from archive member")
    request = saved_window(summary, state, audit)
    config = rolling_solver_config(request)
    sim = scenario.get("simulation_config") or {}
    depot = sim.get("daily_return_depot_id")
    if not depot:
        raise ValueError("Expected an explicit return depot")
    with solver_policy_scope(NO_GUROBI_PROFILE) as usage:
        problem = ProblemBuilder().build_from_scenario(scenario, depot_id=depot,
            service_id=request.service_id, config=config, planning_days=sim["planning_days"])
        problem, _ = _apply_pv_forecast_update(problem, pv)
        _validate_day_ahead_input_contract(problem, audit, scenario_id=request.scenario_id,
            prepared_input_id=request.prepared_input_id, service_date=request.expected_service_date,
            service_id=request.service_id)
        plan = assignment_plan_from_serialized_result(problem, serialized)
        window, effective = capture_window(problem, plan, request, state)
        candidate_window, candidate = capture_window(problem, plan,
            replace(request, stage2_charging_start_policy="fixed_assignment_binary"), state)
        solver_usage = asdict(usage)
    if any(solver_usage[k] for k in ("environment_starts", "model_creations", "optimize_calls", "forbidden_calls")):
        raise RuntimeError("Input preflight reached a forbidden solver entry")
    if candidate_window != window or replace(candidate, stage2_charging_start_policy="none") != effective:
        raise ValueError("Replay policies changed the reconstructed problem or another control")
    report = {
        "status": "INPUT_PREFLIGHT_ONLY", "new_solver_run": False,
        "source_archive_sha256": expected_sha, "source_git": manifest["git"],
        "step_index": step, "current_min": state["current_min"], "evidence_sha256": evidence,
        "solver_usage": solver_usage, "comparison_policies": ["none", "fixed_assignment_binary"],
        "only_config_difference": "stage2_charging_start_policy",
        "comparison_scope": "two_production_state_transformations_before_native_model_construction",
        "controls": {k: getattr(effective, k) for k in ("time_limit_sec", "mip_gap", "random_seed",
            "gurobi_threads", "rolling_current_min", "rolling_execution_minutes", "rolling_lookahead_hours")},
        "source_charging_rows": len(plan.charging_slots), "vehicle_count": len(window.vehicles),
        "restored_connections": len(effective.rolling_connected_charger_by_vehicle),
        "limits": ["No native model constructed; model equivalence and speedup remain untested.",
                   "Diagnostic replay only; the original week and research verdict are unchanged."],
    }
    return window, effective, candidate, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() == args.archive.resolve():
        parser.error("Output must be a new file")
    *_, report = prepare(args.archive, args.archive_sha256, args.step)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({k: report[k] for k in ("status", "step_index", "source_charging_rows", "solver_usage")}))


if __name__ == "__main__":
    main()
