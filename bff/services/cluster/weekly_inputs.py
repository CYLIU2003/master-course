"""Portable, separately hashed execution inputs for dated multi-day runs."""
from __future__ import annotations

import base64
from pathlib import Path, PurePosixPath

from .contracts import digest
from src.optimization.common.date_series import consecutive_service_dates


def execution_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value
            or not path.is_relative_to("data/derived/pv_execution_inputs")
            or path.suffix != ".json"):
        raise ValueError("Actual-PV reference must be a relative immutable execution-input JSON")
    return path


def execution_references(config: dict) -> dict[str, str]:
    contract = config.get("date_series_contract") or {}
    reference = contract.get("pv_execution_input")
    if not reference:
        if contract.get("pv_information_mode") == "training_only_forecast_proxy":
            raise ValueError("Forecast/actual separation requires a hashed actual-PV execution input")
        return {}
    path = str(execution_path(reference["path"]))
    expected = reference.get("sha256", "")
    if len(expected) != 64:
        raise ValueError("Actual-PV execution input requires its Prepare-time SHA-256")
    return {path: expected}


def stage_execution_inputs(configs: list[dict], root: Path) -> dict:
    references = {}
    for config in configs:
        for path, expected in execution_references(config).items():
            if path in references and references[path] != expected:
                raise ValueError("Scenario and prepared actual-PV hashes disagree")
            references[path] = expected
    staged = {}
    for path, expected in references.items():
        source = (root / path).resolve()
        if not source.is_relative_to(root.resolve()):
            raise ValueError("Actual-PV input escaped the repository")
        content = source.read_bytes()
        if digest(content) != expected:
            raise ValueError("Actual-PV execution source changed after Prepare")
        staged[path] = {"sha256": expected, "base64": base64.b64encode(content).decode("ascii")}
    return staged


def install_execution_inputs(bundle: dict, target: Path):
    expected = {}
    import json
    prepared = json.loads(base64.b64decode(bundle["prepared_base64"], validate=True))
    for config in (bundle["scenario"].get("simulation_config") or {}, prepared.get("simulation_config") or {}):
        for path, sha in execution_references(config).items():
            if path in expected and expected[path] != sha:
                raise ValueError("Conflicting actual-PV references")
            expected[path] = sha
    inputs = bundle.get("execution_inputs", {})
    if set(inputs) != set(expected):
        raise ValueError("Execution input inventory does not match prepared references")
    for name, record in inputs.items():
        path = target / str(execution_path(name))
        content = base64.b64decode(record["base64"], validate=True)
        if digest(content) != expected[name] or record["sha256"] != expected[name]:
            raise ValueError("Execution input hash mismatch")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def horizon_summary(scenario: dict, prepared: dict | None = None, kwargs: dict | None = None) -> dict:
    config = (prepared or {}).get("simulation_config") or scenario.get("simulation_config") or {}
    days = int(config.get("planning_days") or 1)
    dates = (consecutive_service_dates(config.get("service_date"), days, config.get("service_dates"))
             if days > 1 or config.get("service_date") or config.get("service_dates") else [])
    controls = kwargs or {}
    return {"scenario_name": scenario.get("meta", {}).get("name", ""),
            "scenario_id": scenario.get("meta", {}).get("id"), "planning_days": days,
            "service_dates": dates, "horizon_hours": days * 24,
            "expected_rolling_windows": days * 24 if controls.get("run_hourly_rolling", True) else 0,
            "trip_count": (prepared or {}).get("trip_count", len((prepared or {}).get("trips", []))),
            "pv_information_mode": (config.get("date_series_contract") or {}).get("pv_information_mode"),
            "input_mode": config.get("multi_day_input_mode"),
            "formal_supported": days == 1,
            "research_status": "MULTIDAY_RESEARCH_BLOCKED" if days > 1 else "SEPARATE_ACCEPTANCE_REQUIRED",
            "mode": controls.get("mode", config.get("solver_mode")),
            "rolling_lookahead_hours": config.get("rolling_lookahead_hours"),
            "run_profile": controls.get("run_profile", "day_ahead_and_hourly_rolling")}
