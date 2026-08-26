"""Run a bounded, interleaved SUNNY/RAIN pure-ICE aggregation A/B study.

This coordinator deliberately reuses the existing isolated-child BFF runner
and the normal BFF Fresh Prepare endpoint.  It does not import a solver or
alter the optimization model.  Its only job is to freeze fresh prepared inputs,
alternate complete A/B pairs between the scenarios, stop starting new children
at the declared deadline, and add a cross-scenario comparison artifact.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_lazy_fragment_performance_diagnostic import (  # noqa: E402
    PURE_ICE_AB_TARGET_PHASE,
    _git_output,
    _load_resumable_pure_ice_case_runs,
    _pure_ice_case_valid,
    _pure_ice_representation_audit_valid,
    _run_pure_ice_case_in_child_process,
    _runtime_environment_snapshot,
    _sha256_file,
    build_pure_ice_alternating_case_plan,
    build_repeated_pure_ice_ab_comparison,
    compile_phase3_pure_ice_ab_request,
    write_repeated_pure_ice_ab_outputs,
)
from scripts.run_frontend_controlled_pv_pair import (  # noqa: E402
    HttpJsonClient,
    _validate_bff_runtime_preflight,
)


SCHEMA_VERSION = "pure_ice_aggregation_weather_ab_v1"
SUNNY_SCENARIO_ID = "771d115b-75b0-49f7-a7f0-25f259a2cd21"
RAIN_SCENARIO_ID = "b23fd26c-1233-4c73-bb9e-bdb8b1584760"
SERVICE_DATE = "2025-08-05"
WEATHER_DATES = {"SUNNY": "2025-08-05", "RAIN": "2025-08-10"}
SCENARIO_ORDER = ("SUNNY", "RAIN")
REQUIRED_FIXED_HASHES = (
    "trip_ids_sha256",
    "vehicle_ids_sha256",
    "charger_ids_sha256",
    "trip_structure_input_sha256",
    "vehicle_input_sha256",
    "charger_input_sha256",
    "depot_input_sha256",
    "vehicle_type_input_sha256",
    "price_input_sha256",
    "price_value_set_sha256",
    "energy_asset_control_input_sha256",
    "objective_weights_sha256",
    "timetable_hash",
    "vehicle_hash",
    "tariff_hash",
    "objective_hash",
)
WEATHER_LINKED_HASHES = (
    "pv_profile_sha256",
    "pv_hash",
    "trip_input_sha256",
    "trip_energy_input_sha256",
    "trip_energy_hash",
)
CROSS_SCENARIO_METRICS = (
    "bev_trip_count",
    "ice_trip_count",
    "used_bev_vehicle_count",
    "used_ice_vehicle_count",
    "total_cost_jpy",
    "fuel_liters",
    "grid_import_kwh",
    "pv_to_bus_kwh",
    "pv_to_bess_kwh",
    "bess_to_bus_kwh",
    "pv_curtail_kwh",
    "peak_grid_kw",
    "minimum_bev_soc_kwh",
    "terminal_bev_soc_kwh_total",
    "terminal_bess_soc_kwh_total",
    "incumbent_objective_jpy",
    "certified_best_bound_jpy",
    "certified_gap_ratio",
    "total_solver_time_sec",
)


@dataclass(frozen=True)
class ScenarioInput:
    """Frozen input contract for one named weather scenario."""

    code_name: str
    scenario_id: str
    prepared_input_id: str
    optimization_request_path: Path


def _write_raw_json_response(path: Path, raw: str) -> None:
    """Persist the exact BFF response only after validating that it is JSON."""

    json.loads(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prepared_input_path(scenario: ScenarioInput) -> Path:
    return (
        REPO_ROOT
        / "output"
        / "prepared_inputs"
        / scenario.scenario_id
        / f"{scenario.prepared_input_id}.json"
    )


def _normalized_request(
    scenario: ScenarioInput,
    *,
    stage1_time_limit_seconds: int,
    stage2_time_limit_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = _read_json(scenario.optimization_request_path)
    if str(source.get("prepared_input_id") or "") != scenario.prepared_input_id:
        raise ValueError(
            f"{scenario.code_name} request prepared_input_id does not match "
            "the frozen prepared input"
        )
    request, transformation = compile_phase3_pure_ice_ab_request(
        source,
        stage1_time_limit_seconds=stage1_time_limit_seconds,
        stage2_time_limit_seconds=stage2_time_limit_seconds,
    )
    _validate_request_controls(request, scenario.code_name)
    return request, transformation


def _validate_prepare_request(
    payload: Mapping[str, Any],
    *,
    code_name: str,
) -> None:
    """Reject a Fresh Prepare payload that changes a fixed study control."""

    settings = dict(payload.get("simulation_settings") or {})
    expected = {
        "selected_depot_ids": ["tsurumaki"],
        "day_type": "WEEKDAY",
        "service_date": SERVICE_DATE,
        "service_dates": [SERVICE_DATE],
        "include_short_turn": True,
        "include_depot_moves": True,
        "include_deadhead": True,
        "allow_intra_depot_route_swap": False,
        "allow_inter_depot_swap": False,
    }
    observed = {key: payload.get(key) for key in expected}
    mismatches = {
        key: {"expected": expected[key], "observed": observed[key]}
        for key in expected
        if observed[key] != expected[key]
    }
    if len(list(payload.get("selected_route_ids") or ())) != 16:
        mismatches["selected_route_ids"] = {
            "expected_count": 16,
            "observed_count": len(list(payload.get("selected_route_ids") or ())),
        }
    fixed_settings = {
        "time_step_min": 15,
        "timestep_min": 15,
        "use_selected_depot_vehicle_inventory": True,
        "use_selected_depot_charger_inventory": True,
        "allow_partial_service": False,
        "fixed_route_band_mode": True,
        "enable_weather_operation_policy": False,
        "random_seed": 42,
        "objective_mode": "total_cost",
        "mip_gap": 0.1,
        "planning_days": 1,
        "planning_horizon_hours": 24.0,
    }
    for key, value in fixed_settings.items():
        if settings.get(key) != value:
            mismatches[f"simulation_settings.{key}"] = {
                "expected": value,
                "observed": settings.get(key),
            }
    expected_weather_date = WEATHER_DATES[code_name]
    if settings.get("counterfactual_pv_source_date") != expected_weather_date:
        mismatches["simulation_settings.counterfactual_pv_source_date"] = {
            "expected": expected_weather_date,
            "observed": settings.get("counterfactual_pv_source_date"),
        }
    if code_name == "SUNNY":
        if settings.get("comparison_role") != "baseline":
            mismatches["simulation_settings.comparison_role"] = {
                "expected": "baseline",
                "observed": settings.get("comparison_role"),
            }
        if settings.get("allow_fixed_weekday_timetable_pv_counterfactual") is not False:
            mismatches[
                "simulation_settings.allow_fixed_weekday_timetable_pv_counterfactual"
            ] = {"expected": False, "observed": settings.get("allow_fixed_weekday_timetable_pv_counterfactual")}
    else:
        rain_expected = {
            "comparison_role": "pv_curve_counterfactual",
            "allow_fixed_weekday_timetable_pv_counterfactual": True,
        }
        for key, value in rain_expected.items():
            if settings.get(key) != value:
                mismatches[f"simulation_settings.{key}"] = {
                    "expected": value,
                    "observed": settings.get(key),
                }
    if mismatches:
        raise ValueError(
            f"{code_name} Fresh Prepare request violates the fixed protocol: "
            + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        )


def prepare_fresh_weather_inputs(
    *,
    base_url: str,
    output_dir: Path,
    sunny_prepare_request_path: Path,
    rain_prepare_request_path: Path,
    optimization_template_path: Path,
    frozen_sha: str,
    study_started_at_utc: datetime,
) -> tuple[dict[str, ScenarioInput], dict[str, Any]]:
    """Call the canonical BFF Prepare endpoint and freeze its exact evidence."""

    if output_dir.exists():
        raise FileExistsError(f"Fresh Prepare output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    preparation_dir = output_dir / "preparation"
    client = HttpJsonClient(base_url)
    try:
        health, health_raw = client.request_json("GET", "/health")
        _write_raw_json_response(preparation_dir / "bff_health_response.json", health_raw)
        if health.get("status") != "ok":
            raise RuntimeError(f"BFF health check failed: {health}")
        preflight, preflight_raw = client.request_json(
            "GET", "/api/research/git-preflight"
        )
        _write_raw_json_response(
            preparation_dir / "bff_runtime_git_preflight_response.json",
            preflight_raw,
        )
        _validate_bff_runtime_preflight(preflight, frozen_git_sha=frozen_sha)

        template = _read_json(optimization_template_path)
        prepared_inputs: dict[str, ScenarioInput] = {}
        prepare_records: dict[str, Any] = {}
        sources = {
            "SUNNY": (SUNNY_SCENARIO_ID, sunny_prepare_request_path),
            "RAIN": (RAIN_SCENARIO_ID, rain_prepare_request_path),
        }
        for code, (scenario_id, request_path) in sources.items():
            payload = _read_json(request_path)
            _validate_prepare_request(payload, code_name=code)
            scenario_dir = preparation_dir / code
            _write_json(scenario_dir / "frontend_prepare_request.json", payload)
            response, raw = client.request_json(
                "POST",
                f"/api/scenarios/{scenario_id}/simulation/prepare",
                payload,
                timeout_seconds=180.0,
            )
            _write_raw_json_response(
                scenario_dir / "frontend_prepare_response.json", raw
            )
            prepared_input_id = str(response.get("preparedInputId") or "").strip()
            checks = {
                "ready": response.get("ready") is True,
                "prepared_input_id_present": bool(prepared_input_id),
                "route_count_16": int(response.get("routeCount") or 0) == 16,
                "trip_count_264": int(response.get("tripCount") or 0) == 264,
                "weekday_service": list(response.get("serviceIds") or []) == ["WEEKDAY"],
            }
            if not all(checks.values()):
                raise RuntimeError(
                    f"{code} Fresh Prepare response failed: "
                    + json.dumps(checks, ensure_ascii=False, sort_keys=True)
                )
            optimization_request = dict(template)
            optimization_request["prepared_input_id"] = prepared_input_id
            optimization_path = scenario_dir / "frontend_optimization_request.json"
            _write_json(optimization_path, optimization_request)
            prepared_inputs[code] = ScenarioInput(
                code, scenario_id, prepared_input_id, optimization_path
            )
            prepare_records[code] = {
                "scenario_id": scenario_id,
                "prepared_input_id": prepared_input_id,
                "prepare_request_sha256": _sha256_file(
                    scenario_dir / "frontend_prepare_request.json"
                ),
                "prepare_response_sha256": _sha256_file(
                    scenario_dir / "frontend_prepare_response.json"
                ),
                "response_checks": checks,
            }
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "study_started_at_utc": study_started_at_utc.isoformat(),
            "prepared_at_utc": _utc_now().isoformat(),
            "git_sha": frozen_sha,
            "base_url": base_url.rstrip("/"),
            "optimization_template_sha256": _sha256_file(optimization_template_path),
            "scenarios": prepare_records,
        }
        _write_json(preparation_dir / "fresh_prepare_manifest.json", evidence)
        return prepared_inputs, evidence
    except Exception as exc:
        _write_json(
            preparation_dir / "fresh_prepare_failure.json",
            {
                "schema_version": SCHEMA_VERSION,
                "status": "FAIL_CORRECTNESS",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "failed_at_utc": _utc_now().isoformat(),
                "git_sha": frozen_sha,
            },
        )
        _write_json(
            output_dir / "artifact_hashes.json",
            {"schema_version": "artifact_hashes_v1", "sha256": _artifact_hashes(output_dir)},
        )
        raise


def _validate_request_controls(request: Mapping[str, Any], code_name: str) -> None:
    """Reject any A/B request that changes a non-representation control."""

    expected = {
        "mode": PURE_ICE_AB_TARGET_PHASE,
        "service_id": "WEEKDAY",
        "depot_id": "tsurumaki",
        "time_step_min": 15,
        "timestep_min": 15,
        "run_profile": "day_ahead_and_hourly_rolling",
        "run_hourly_rolling": True,
        "rolling_execution_minutes": 60,
        "gurobi_threads": 1,
        "stage1_best_obj_stop_enabled": False,
        "stage1_powertrain_selector_strengthening": False,
        "research_run": True,
        "rebuild_dispatch": False,
        "force_reprepare": False,
        "use_existing_duties": False,
    }
    mismatches = {
        key: {"expected": value, "observed": request.get(key)}
        for key, value in expected.items()
        if request.get(key) != value
    }
    if mismatches:
        raise ValueError(
            f"{code_name} optimization request violates frozen A/B controls: "
            + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        )
    if int(request.get("stage1_stage2_candidate_limit") or 0) != 1:
        raise ValueError(f"{code_name} requires stage1_stage2_candidate_limit=1")
    if int(request.get("stage1_composition_search_radius") or -1) != 0:
        raise ValueError(f"{code_name} requires stage1_composition_search_radius=0")


def _prepared_descriptor(scenario: ScenarioInput) -> dict[str, Any]:
    """Record the materialized scope without treating an old ID as evidence."""

    path = _prepared_input_path(scenario)
    if not path.is_file():
        raise FileNotFoundError(f"prepared input is missing: {path}")
    payload = _read_json(path)
    simulation_config = dict(payload.get("simulation_config") or {})
    expected_weather_date = WEATHER_DATES[scenario.code_name]
    checks = {
        "scenario_id": payload.get("scenario_id") == scenario.scenario_id,
        "prepared_input_id": payload.get("prepared_input_id") == scenario.prepared_input_id,
        "service_date": payload.get("service_date") == SERVICE_DATE,
        "weekday_service": list(payload.get("service_ids") or []) == ["WEEKDAY"],
        "tsurumaki_primary_depot": payload.get("primary_depot_id") == "tsurumaki",
        "trip_count_264": int(payload.get("trip_count") or 0) == 264,
        "scenario_fleet_contract_v2_present": (
            "scenario_fleet_contract_v2"
            in json.dumps(payload, ensure_ascii=False, sort_keys=True)
        ),
        "time_step_min_15": simulation_config.get("time_step_min") == 15,
        "timestep_min_15": simulation_config.get("timestep_min") == 15,
        "weather_observation_date": (
            simulation_config.get("weather_observation_date") == expected_weather_date
        ),
        "counterfactual_pv_source_date": (
            simulation_config.get("counterfactual_pv_source_date")
            == expected_weather_date
        ),
    }
    if scenario.code_name == "SUNNY":
        checks["sunny_baseline_role"] = (
            simulation_config.get("comparison_role") == "baseline"
            and simulation_config.get("allow_fixed_weekday_timetable_pv_counterfactual")
            is False
        )
    if scenario.code_name == "RAIN":
        checks["rain_fixed_weekday_counterfactual"] = bool(
            simulation_config.get("allow_fixed_weekday_timetable_pv_counterfactual")
            and simulation_config.get("calendar_policy")
            == "fixed_weekday_timetable_pv_counterfactual"
            and simulation_config.get("comparison_role") == "pv_curve_counterfactual"
        )
    if not all(checks.values()):
        raise RuntimeError(
            f"{scenario.code_name} prepared-input preflight failed: "
            + json.dumps(checks, ensure_ascii=False, sort_keys=True)
        )
    weather_fields = {
        key: value
        for key, value in simulation_config.items()
        if any(token in key.lower() for token in ("weather", "pv", "comparison", "counterfactual", "calendar"))
    }
    return {
        "scenario_id": scenario.scenario_id,
        "prepared_input_id": scenario.prepared_input_id,
        "prepared_input_path": str(path.resolve()),
        "prepared_source_sha256": _sha256_file(path),
        "prepared_at": payload.get("prepared_at"),
        "service_date": payload.get("service_date"),
        "service_ids": payload.get("service_ids"),
        "primary_depot_id": payload.get("primary_depot_id"),
        "trip_count": payload.get("trip_count"),
        "route_ids_sha256": _canonical_hash(payload.get("route_ids") or []),
        "trips_sha256": _canonical_hash(payload.get("trips") or []),
        "trip_ids_sha256": _canonical_hash(
            [str(dict(item).get("trip_id") or "") for item in payload.get("trips") or []]
        ),
        "trip_structure_without_weather_energy_sha256": _canonical_hash(
            _remove_weather_linked_fields(payload.get("trips") or [])
        ),
        "vehicles_sha256": _canonical_hash(payload.get("vehicles") or []),
        "chargers_sha256": _canonical_hash(payload.get("chargers") or []),
        "depots_sha256": _canonical_hash(payload.get("depots") or []),
        "simulation_config_without_weather_sha256": _canonical_hash(
            _remove_weather_linked_fields(simulation_config)
        ),
        "scenario_overlay_without_weather_sha256": _canonical_hash(
            _remove_weather_linked_fields(payload.get("scenario_overlay") or {})
        ),
        "weather_and_counterfactual_fields": weather_fields,
        "preflight_checks": checks,
    }


def _remove_weather_linked_fields(value: Any) -> Any:
    """Remove only declared weather/PV and weather-energy leaves for preflight."""

    tokens = ("weather", "pv", "counterfactual", "comparison", "calendar", "trip_energy")
    if isinstance(value, Mapping):
        return {
            str(key): _remove_weather_linked_fields(child)
            for key, child in value.items()
            if not any(token in str(key).lower() for token in tokens)
        }
    if isinstance(value, list):
        return [_remove_weather_linked_fields(item) for item in value]
    return value


def build_prepared_input_contract(
    descriptors: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Fail before solving if SUNNY/RAIN drift beyond weather-linked inputs."""

    keys = (
        "route_ids_sha256",
        "trip_ids_sha256",
        "trip_structure_without_weather_energy_sha256",
        "vehicles_sha256",
        "chargers_sha256",
        "depots_sha256",
        "simulation_config_without_weather_sha256",
        "scenario_overlay_without_weather_sha256",
    )
    checks = {
        key: descriptors["SUNNY"].get(key) == descriptors["RAIN"].get(key)
        for key in keys
    }
    return {
        "fixed_prepared_content_checks": checks,
        "all_fixed_prepared_content_matches": all(checks.values()),
        "sunny_weather_fields": descriptors["SUNNY"].get("weather_and_counterfactual_fields"),
        "rain_weather_fields": descriptors["RAIN"].get("weather_and_counterfactual_fields"),
    }


def build_interleaved_case_schedule(repetitions: int = 5) -> list[dict[str, Any]]:
    """Return SUN AB, RAIN AB, SUN BA, RAIN BA, ... without solver work."""

    per_scenario = build_pure_ice_alternating_case_plan(repetitions)
    schedule: list[dict[str, Any]] = []
    for pair_index in range(1, repetitions + 1):
        pair_runs = [
            item for item in per_scenario if int(item["pair_index"]) == pair_index
        ]
        if len(pair_runs) != 2:
            raise RuntimeError(f"invalid pair plan for pair {pair_index}")
        for scenario_code in SCENARIO_ORDER:
            for run in pair_runs:
                schedule.append({"scenario": scenario_code, **run})
    return schedule


def _assert_clean_frozen_sha(expected_sha: str | None = None) -> str:
    if _git_output("status", "--porcelain"):
        raise RuntimeError("weather A/B requires a clean Git worktree")
    observed = _git_output("rev-parse", "HEAD")
    if expected_sha is not None and observed != expected_sha:
        raise RuntimeError(
            f"weather A/B Git SHA drifted: expected {expected_sha}, got {observed}"
        )
    return observed


def _scenario_output_dir(output_dir: Path, code_name: str) -> Path:
    return output_dir / "scenarios" / code_name


def _load_completed_case_runs(
    *,
    scenario: ScenarioInput,
    scenario_dir: Path,
    expected_sha: str,
    expected_prepared_sha256: str,
    plan: Iterable[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    if not scenario_dir.exists():
        return {}
    return _load_resumable_pure_ice_case_runs(
        output_dir=scenario_dir,
        plan=plan,
        expected_git_sha=expected_sha,
        expected_prepared_input_sha256=expected_prepared_sha256,
    )


def _case_run_directory(scenario_dir: Path, planned_run: Mapping[str, Any]) -> Path:
    return scenario_dir / "runs" / (
        f"{int(planned_run['run_index']):02d}_{planned_run['label']}"
    )


def _persist_case_metrics(
    run_directory: Path,
    metrics: Mapping[str, Any],
) -> None:
    _write_json(run_directory / "case_metrics.json", metrics)


def _current_progress(
    *,
    schedule: Iterable[Mapping[str, Any]],
    completed: Mapping[str, Mapping[int, Mapping[str, Any]]],
    status: str,
    reason: str | None,
) -> dict[str, Any]:
    completed_indices = {
        scenario: sorted(int(index) for index in runs)
        for scenario, runs in completed.items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "planned_case_count": len(list(schedule)),
        "completed_run_indices": completed_indices,
        "completed_case_count": sum(len(indices) for indices in completed_indices.values()),
        "updated_at_utc": _utc_now().isoformat(),
    }


def _case_input_hashes(case_runs: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [dict(item.get("metrics") or {}) for item in case_runs]
    if not metrics:
        return {}
    hashes = [dict(dict(metric.get("provenance") or {}).get("input_hashes") or {}) for metric in metrics]
    keys = sorted({key for item in hashes for key in item})
    return {
        key: {
            "values": sorted({str(item.get(key)) for item in hashes}),
            "stable_within_scenario": len({str(item.get(key)) for item in hashes}) == 1,
            "value": hashes[0].get(key),
        }
        for key in keys
    }


def build_cross_scenario_input_contract(
    scenario_runs: Mapping[str, Iterable[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Verify that only declared weather-linked canonical inputs differ."""

    summaries = {
        code: _case_input_hashes(runs)
        for code, runs in scenario_runs.items()
    }
    fixed_checks: dict[str, bool] = {}
    for key in REQUIRED_FIXED_HASHES:
        sunny = summaries.get("SUNNY", {}).get(key, {})
        rain = summaries.get("RAIN", {}).get(key, {})
        fixed_checks[key] = bool(
            sunny.get("stable_within_scenario")
            and rain.get("stable_within_scenario")
            and sunny.get("value") is not None
            and sunny.get("value") == rain.get("value")
        )
    weather_differences = {
        key: {
            "sunny": dict(summaries.get("SUNNY", {}).get(key) or {}).get("value"),
            "rain": dict(summaries.get("RAIN", {}).get(key) or {}).get("value"),
        }
        for key in WEATHER_LINKED_HASHES
        if dict(summaries.get("SUNNY", {}).get(key) or {}).get("value")
        != dict(summaries.get("RAIN", {}).get(key) or {}).get("value")
    }
    pv_sunny = dict(summaries.get("SUNNY", {}).get("pv_profile_sha256") or {}).get("value")
    pv_rain = dict(summaries.get("RAIN", {}).get("pv_profile_sha256") or {}).get("value")
    return {
        "fixed_control_hashes": fixed_checks,
        "all_fixed_controls_match": all(fixed_checks.values()),
        "weather_linked_hash_differences": weather_differences,
        "pv_profile_hashes_differ": bool(pv_sunny and pv_rain and pv_sunny != pv_rain),
        "per_scenario_hashes": summaries,
    }


def _median(values: Iterable[Any]) -> float | None:
    numeric = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return float(statistics.median(numeric)) if numeric else None


def _scenario_representation_summary(case_runs: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, float | None]]:
    groups: dict[str, list[Mapping[str, Any]]] = {"discrete": [], "pure_aggregate": []}
    for run in case_runs:
        groups[str(run.get("representation"))].append(dict(run.get("metrics") or {}))
    result: dict[str, dict[str, float | None]] = {}
    for representation, metrics in groups.items():
        result[representation] = {}
        for metric in CROSS_SCENARIO_METRICS:
            result[representation][metric] = _median(
                _metric_value(item, metric) for item in metrics
            )
    return result


def _metric_value(metrics: Mapping[str, Any], metric: str) -> Any:
    if metric in {"incumbent_objective_jpy", "certified_best_bound_jpy", "certified_gap_ratio"}:
        return dict(metrics.get("solve_outcome") or {}).get(metric)
    if metric == "total_solver_time_sec":
        return dict(metrics.get("timing") or {}).get(metric)
    return dict(metrics.get("operational_outcomes") or {}).get(metric)


def build_cross_scenario_comparison(
    *,
    scenario_runs: Mapping[str, Iterable[Mapping[str, Any]]],
    input_contract: Mapping[str, Any],
) -> dict[str, Any]:
    summaries = {
        code: _scenario_representation_summary(runs)
        for code, runs in scenario_runs.items()
    }
    rows: list[dict[str, Any]] = []
    for representation in ("discrete", "pure_aggregate"):
        for metric in CROSS_SCENARIO_METRICS:
            sunny = summaries["SUNNY"][representation].get(metric)
            rain = summaries["RAIN"][representation].get(metric)
            rows.append(
                {
                    "representation": representation,
                    "metric": metric,
                    "sunny_median": sunny,
                    "rain_median": rain,
                    "rain_minus_sunny": (
                        None if sunny is None or rain is None else rain - sunny
                    ),
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now().isoformat(),
        "claim_scope": (
            "Cross-scenario descriptive comparison. Different weather/PV "
            "inputs are expected; it is not an optimality or causal claim."
        ),
        "input_contract": dict(input_contract),
        "summaries": summaries,
        "rows": rows,
    }


def write_cross_scenario_outputs(comparison: Mapping[str, Any], output_dir: Path) -> None:
    _write_json(output_dir / "weather_cross_scenario_comparison.json", comparison)
    rows = [dict(item) for item in comparison.get("rows") or []]
    with (output_dir / "weather_cross_scenario_comparison.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# SUNNY/RAIN pure-ICE aggregation comparison",
        "",
        f"- fixed controls match: `{dict(comparison['input_contract'])['all_fixed_controls_match']}`",
        f"- PV hashes differ: `{dict(comparison['input_contract'])['pv_profile_hashes_differ']}`",
        "- scope: descriptive, median over five completed runs per representation.",
        "",
        "| Representation | Metric | SUNNY median | RAIN median | RAIN - SUNNY |",
        "|---|---|---:|---:|---:|",
    ]
    lines.extend(
        "| {representation} | {metric} | {sunny_median} | {rain_median} | {rain_minus_sunny} |".format(**row)
        for row in rows
    )
    (output_dir / "weather_cross_scenario_comparison.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _artifact_hashes(output_dir: Path) -> dict[str, str]:
    paths = sorted(
        path for path in output_dir.rglob("*.json")
        if path.name not in {"artifact_hashes.json"}
    )
    paths.extend(sorted(output_dir.rglob("*.csv")))
    paths.extend(sorted(output_dir.rglob("*.md")))
    return {
        str(path.relative_to(output_dir)).replace("\\", "/"): _sha256_file(path)
        for path in paths
    }


def run_weather_ab(
    *,
    sunny: ScenarioInput,
    rain: ScenarioInput,
    output_dir: Path,
    stage1_time_limit_seconds: int,
    stage2_time_limit_seconds: int,
    repetitions: int = 5,
    deadline_hours: float = 24.0,
    new_work_cutoff_hours: float = 20.0,
    small_exact_parity_passed: bool = False,
    resume: bool = False,
    fresh_prepare_evidence: Mapping[str, Any] | None = None,
    study_started_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Execute the two-scenario schedule and fail closed on any bad child."""

    if repetitions != 5:
        raise ValueError("the weather A/B protocol requires exactly five pairs")
    if not small_exact_parity_passed:
        raise ValueError(
            "weather A/B requires a focused small exact-parity regression before "
            "a 264-trip execution"
        )
    if not (0.0 < new_work_cutoff_hours < deadline_hours):
        raise ValueError("cutoff must be positive and earlier than the deadline")
    scenarios = {"SUNNY": sunny, "RAIN": rain}
    expected_ids = {"SUNNY": SUNNY_SCENARIO_ID, "RAIN": RAIN_SCENARIO_ID}
    if {code: item.scenario_id for code, item in scenarios.items()} != expected_ids:
        raise ValueError("scenario IDs must be the protocol-fixed SUNNY and RAIN IDs")
    frozen_sha = _assert_clean_frozen_sha()
    manifest_path = output_dir / "request_manifest.json"
    if not resume:
        if output_dir.exists():
            unexpected = [path.name for path in output_dir.iterdir() if path.name != "preparation"]
            if unexpected:
                raise FileExistsError(
                    "weather A/B output directory has non-Prepare content: "
                    + ", ".join(sorted(unexpected))
                )
        else:
            output_dir.mkdir(parents=True, exist_ok=False)
    plan = build_pure_ice_alternating_case_plan(repetitions)
    schedule = build_interleaved_case_schedule(repetitions)
    try:
        descriptors = {code: _prepared_descriptor(item) for code, item in scenarios.items()}
        prepared_content_contract = build_prepared_input_contract(descriptors)
        if not prepared_content_contract["all_fixed_prepared_content_matches"]:
            raise RuntimeError(
                "SUNNY/RAIN prepared inputs differ outside permitted weather-linked "
                "content: "
                + json.dumps(
                    prepared_content_contract["fixed_prepared_content_checks"],
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        requests: dict[str, dict[str, Any]] = {}
        transformations: dict[str, dict[str, Any]] = {}
        for code, scenario in scenarios.items():
            requests[code], transformations[code] = _normalized_request(
                scenario,
                stage1_time_limit_seconds=stage1_time_limit_seconds,
                stage2_time_limit_seconds=stage2_time_limit_seconds,
            )
    except Exception as exc:
        if not resume:
            _write_json(
                output_dir / "preflight_failure.json",
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "FAIL_CORRECTNESS",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "failed_at_utc": _utc_now().isoformat(),
                    "git_sha": frozen_sha,
                    "fresh_prepare_evidence": dict(fresh_prepare_evidence or {}),
                },
            )
            _write_json(
                output_dir / "artifact_hashes.json",
                {"schema_version": "artifact_hashes_v1", "sha256": _artifact_hashes(output_dir)},
            )
        raise
    if resume:
        manifest = _read_json(manifest_path)
        if str(manifest.get("git_sha") or "") != frozen_sha:
            raise RuntimeError("resume SHA does not match the original experiment")
        recorded_controls = dict(manifest.get("solver_controls") or {})
        if (
            int(recorded_controls.get("stage1_time_limit_seconds") or 0)
            != stage1_time_limit_seconds
            or int(recorded_controls.get("stage2_time_limit_seconds") or 0)
            != stage2_time_limit_seconds
        ):
            raise RuntimeError("resume stage time limits do not match the frozen manifest")
        started_at = datetime.fromisoformat(str(manifest["started_at_utc"]))
        expected = dict(manifest.get("prepared_inputs") or {})
        if any(expected.get(code) != descriptors[code] for code in scenarios):
            raise RuntimeError("resume prepared-input descriptor drifted")
        expected_request_hashes = dict(
            manifest.get("frozen_optimization_request_sha256") or {}
        )
        observed_request_hashes = {
            code: _sha256_file(_scenario_output_dir(output_dir, code) / "frozen_optimization_request.json")
            for code in scenarios
        }
        if observed_request_hashes != expected_request_hashes:
            raise RuntimeError("resume optimization request differs from the frozen manifest")
    else:
        started_at = study_started_at_utc or _utc_now()
        if started_at.tzinfo is None:
            raise ValueError("study_started_at_utc must be timezone-aware")
        for code, request in requests.items():
            scenario_dir = _scenario_output_dir(output_dir, code)
            _write_json(scenario_dir / "frozen_optimization_request.json", request)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": started_at.isoformat(),
            "started_at_utc": started_at.isoformat(),
            "new_work_cutoff_at_utc": (started_at + timedelta(hours=new_work_cutoff_hours)).isoformat(),
            "deadline_at_utc": (started_at + timedelta(hours=deadline_hours)).isoformat(),
            "git_sha": frozen_sha,
            "git_dirty": False,
            "runtime_environment": _runtime_environment_snapshot(),
            "scenarios": {
                code: {
                    "scenario_id": item.scenario_id,
                    "weather_date": WEATHER_DATES[code],
                    "service_date": SERVICE_DATE,
                    "service_id": "WEEKDAY",
                    "depot_id": "tsurumaki",
                }
                for code, item in scenarios.items()
            },
            "prepared_inputs": descriptors,
            "prepared_content_contract": prepared_content_contract,
            "fresh_prepare_evidence": dict(fresh_prepare_evidence or {}),
            "frozen_optimization_request_sha256": {},
            "solver_controls": {
                "random_seed": requests["SUNNY"].get("random_seed"),
                "gurobi_threads": 1,
                "mip_gap": requests["SUNNY"].get("mip_gap"),
                "stage1_time_limit_seconds": stage1_time_limit_seconds,
                "stage2_time_limit_seconds": stage2_time_limit_seconds,
                "stage1_best_obj_stop_enabled": False,
                "stage1_powertrain_selector_strengthening": False,
                "time_step_min": 15,
                "rolling_execution_minutes": 60,
            },
            "phase3_request_transformations": transformations,
            "execution_contract": {
                "scenario_order_within_pair": list(SCENARIO_ORDER),
                "per_scenario_pair_order": ["AB", "BA", "AB", "BA", "AB"],
                "interleaved_case_schedule": schedule,
                "separate_child_process_per_run": True,
                "fallback_forbidden": True,
                "post_solve_repair_forbidden": True,
                "synthetic_pv_fallback_forbidden": True,
                "stage1_objective_proxy_forbidden": True,
                "small_exact_parity_passed": True,
            },
        }
        manifest["frozen_optimization_request_sha256"] = {
            code: _sha256_file(
                _scenario_output_dir(output_dir, code) / "frozen_optimization_request.json"
            )
            for code in scenarios
        }
        _write_json(manifest_path, manifest)

    deadline_at = datetime.fromisoformat(str(manifest["deadline_at_utc"]))
    cutoff_at = datetime.fromisoformat(str(manifest["new_work_cutoff_at_utc"]))
    completed: dict[str, dict[int, dict[str, Any]]] = {}
    for code, scenario in scenarios.items():
        completed[code] = _load_completed_case_runs(
            scenario=scenario,
            scenario_dir=_scenario_output_dir(output_dir, code),
            expected_sha=frozen_sha,
            expected_prepared_sha256=str(descriptors[code]["prepared_source_sha256"]),
            plan=plan,
        )

    status = "COMPLETED"
    reason: str | None = None
    for scheduled in schedule:
        code = str(scheduled["scenario"])
        run_index = int(scheduled["run_index"])
        if run_index in completed[code]:
            continue
        now = _utc_now()
        if now >= deadline_at:
            status = "INTERRUPTED"
            reason = "deadline_reached_before_new_child"
            break
        if now >= cutoff_at:
            status = "INTERRUPTED"
            reason = "new_work_cutoff_reached"
            break
        _assert_clean_frozen_sha(frozen_sha)
        scenario = scenarios[code]
        scenario_dir = _scenario_output_dir(output_dir, code)
        run_directory = _case_run_directory(scenario_dir, scheduled)
        run_directory.mkdir(parents=True, exist_ok=False)
        request_path = scenario_dir / "frozen_optimization_request.json"
        try:
            child = _run_pure_ice_case_in_child_process(
                scenario_id=scenario.scenario_id,
                prepared_input_id=scenario.prepared_input_id,
                optimization_request_path=request_path,
                representation=str(scheduled["representation"]),
                run_directory=run_directory,
                expected_git_sha=frozen_sha,
                execution_deadline_utc=deadline_at,
            )
        except RuntimeError as exc:
            if "declared execution deadline" not in str(exc):
                raise
            status = "INTERRUPTED"
            reason = "deadline_reached_during_child"
            _write_json(
                run_directory / "interrupted_child.json",
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": status,
                    "reason": reason,
                    "interrupted_at_utc": _utc_now().isoformat(),
                },
            )
            break
        metrics = dict(child["metrics"])
        observed_hash = dict(dict(metrics.get("provenance") or {}).get("input_hashes") or {}).get("prepared_source_sha256")
        if observed_hash != descriptors[code]["prepared_source_sha256"]:
            raise RuntimeError("child prepared-source hash does not match frozen descriptor")
        _persist_case_metrics(run_directory, metrics)
        completed[code][run_index] = {**scheduled, **child, "metrics": metrics}
        if not (
            _pure_ice_case_valid(metrics)
            and _pure_ice_representation_audit_valid(metrics, str(scheduled["representation"]))
        ):
            status = "FAIL_CORRECTNESS"
            reason = f"invalid_{code}_run_{run_index:02d}"
        _write_json(
            output_dir / "execution_progress.json",
            _current_progress(
                schedule=schedule,
                completed=completed,
                status=status,
                reason=reason,
            ),
        )
        if status != "COMPLETED":
            break

    _assert_clean_frozen_sha(frozen_sha)
    scenario_runs = {
        code: [completed[code][index] for index in sorted(completed[code])]
        for code in scenarios
    }
    if status == "COMPLETED" and all(len(runs) == 10 for runs in scenario_runs.values()):
        comparisons = {
            code: build_repeated_pure_ice_ab_comparison(
                scenario_runs[code], small_exact_parity_passed=True
            )
            for code in scenarios
        }
        if any(result["verdict"] == "FAIL_CORRECTNESS" for result in comparisons.values()):
            status = "FAIL_CORRECTNESS"
            reason = "scenario_comparison_correctness_failed"
        for code, comparison in comparisons.items():
            write_repeated_pure_ice_ab_outputs(comparison, _scenario_output_dir(output_dir, code))
        input_contract = build_cross_scenario_input_contract(scenario_runs)
        if not input_contract["all_fixed_controls_match"] or not input_contract["pv_profile_hashes_differ"]:
            status = "FAIL_CORRECTNESS"
            reason = "cross_scenario_input_contract_failed"
        cross = build_cross_scenario_comparison(
            scenario_runs=scenario_runs,
            input_contract=input_contract,
        )
        write_cross_scenario_outputs(cross, output_dir)
    else:
        comparisons = {}
        input_contract = build_cross_scenario_input_contract(scenario_runs)
        _write_json(
            output_dir / "interrupted_execution.json",
            {
                "schema_version": SCHEMA_VERSION,
                "status": status,
                "reason": reason,
                "runtime_claim": "DIAGNOSTIC_ONLY_INSUFFICIENT_FIVE_PAIRS",
                "completed_case_counts": {code: len(runs) for code, runs in scenario_runs.items()},
                "input_contract": input_contract,
            },
        )

    result = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "git_sha": frozen_sha,
        "completed_case_counts": {code: len(runs) for code, runs in scenario_runs.items()},
        "scenario_verdicts": {code: comparison.get("verdict") for code, comparison in comparisons.items()},
        "input_contract": input_contract,
        "prepared_content_contract": prepared_content_contract,
        "completed_at_utc": _utc_now().isoformat(),
    }
    _write_json(output_dir / "weather_ab_result.json", result)
    _write_json(
        output_dir / "execution_progress.json",
        _current_progress(
            schedule=schedule,
            completed=completed,
            status=status,
            reason=reason,
        ),
    )
    _write_json(
        output_dir / "artifact_hashes.json",
        {"schema_version": "artifact_hashes_v1", "sha256": _artifact_hashes(output_dir)},
    )
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--sunny-prepare-request", type=Path)
    parser.add_argument("--rain-prepare-request", type=Path)
    parser.add_argument("--optimization-request-template", type=Path)
    parser.add_argument("--stage1-time-limit-seconds", required=True, type=int)
    parser.add_argument("--stage2-time-limit-seconds", required=True, type=int)
    parser.add_argument("--deadline-hours", type=float, default=24.0)
    parser.add_argument("--new-work-cutoff-hours", type=float, default=20.0)
    parser.add_argument(
        "--small-exact-parity-passed",
        action="store_true",
        help="Record the required focused exact-parity regression precondition.",
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir.resolve()
    if args.resume:
        manifest = _read_json(output_dir / "request_manifest.json")
        prepared = dict(manifest.get("prepared_inputs") or {})
        sunny = ScenarioInput(
            "SUNNY",
            SUNNY_SCENARIO_ID,
            str(dict(prepared.get("SUNNY") or {}).get("prepared_input_id") or ""),
            _scenario_output_dir(output_dir, "SUNNY") / "frozen_optimization_request.json",
        )
        rain = ScenarioInput(
            "RAIN",
            RAIN_SCENARIO_ID,
            str(dict(prepared.get("RAIN") or {}).get("prepared_input_id") or ""),
            _scenario_output_dir(output_dir, "RAIN") / "frozen_optimization_request.json",
        )
        prepare_evidence = dict(manifest.get("fresh_prepare_evidence") or {})
    else:
        required = {
            "--sunny-prepare-request": args.sunny_prepare_request,
            "--rain-prepare-request": args.rain_prepare_request,
            "--optimization-request-template": args.optimization_request_template,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "Fresh Prepare is required before any child process; missing "
                + ", ".join(missing)
            )
        study_started_at = _utc_now()
        frozen_sha = _assert_clean_frozen_sha()
        prepared_inputs, prepare_evidence = prepare_fresh_weather_inputs(
            base_url=args.base_url,
            output_dir=output_dir,
            sunny_prepare_request_path=args.sunny_prepare_request.resolve(),
            rain_prepare_request_path=args.rain_prepare_request.resolve(),
            optimization_template_path=args.optimization_request_template.resolve(),
            frozen_sha=frozen_sha,
            study_started_at_utc=study_started_at,
        )
        sunny = prepared_inputs["SUNNY"]
        rain = prepared_inputs["RAIN"]
    result = run_weather_ab(
        sunny=sunny,
        rain=rain,
        output_dir=output_dir,
        stage1_time_limit_seconds=args.stage1_time_limit_seconds,
        stage2_time_limit_seconds=args.stage2_time_limit_seconds,
        deadline_hours=args.deadline_hours,
        new_work_cutoff_hours=args.new_work_cutoff_hours,
        small_exact_parity_passed=bool(args.small_exact_parity_passed),
        resume=args.resume,
        fresh_prepare_evidence=prepare_evidence,
        study_started_at_utc=None if args.resume else study_started_at,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
