"""Helpers for controlled weather-case scenario comparisons.

The comparison keeps operational and economic assumptions fixed while
preserving each case's service date and weather/PV input series.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping


WEATHER_INPUT_SIMULATION_KEYS = frozenset(
    {
        "service_date",
        "service_dates",
        "pv_profile_id",
        "weather_mode",
        "weather_factor_scalar",
        "weather_factor_hourly",
        "weather_proxy_forecast_path",
        "weather_proxy_daily_csv_path",
        "weather_proxy_station_id",
        "weather_proxy_station_name",
        "weather_reference_date",
        "solcast_proxy_issue_date",
        "solcast_typical_curve_path",
        "solcast_typical_weather_class",
        "weather_operation_mode",
    }
)
WEATHER_INPUT_ASSET_KEYS = frozenset(
    {
        "pv_generation_kwh_by_slot",
        "capacity_factor_by_slot",
        "pv_case_id",
        "pv_profile_source",
        "pv_profile_dates",
        "pv_generation_kwh_by_date",
        "pv_capacity_factor_by_date",
    }
)
WEATHER_INPUT_OVERLAY_COST_KEYS = frozenset(
    {
        "pv_profile_id",
        "weather_mode",
        "weather_factor_scalar",
        "weather_factor_hourly",
    }
)
OVERLAY_IDENTITY_KEYS = frozenset(
    {"scenario_id", "dataset_id", "dataset_version", "depot_ids", "route_ids"}
)
TIME_AXIS_KEYS = frozenset(
    {"start_time", "end_time", "planning_horizon_hours", "planning_days"}
)


def align_simulation_config(
    reference_config: Mapping[str, Any],
    target_config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Copy control variables from reference while retaining target weather data."""
    reference = _require_mapping(reference_config, "reference_config")
    target = _require_mapping(target_config, "target_config")
    _validate_time_axis_and_pv_slots(reference, target)
    aligned = deepcopy(reference)
    _restore_keys(aligned, target, WEATHER_INPUT_SIMULATION_KEYS)
    aligned["depot_energy_assets"] = _align_asset_collection(
        reference.get("depot_energy_assets"),
        target.get("depot_energy_assets"),
    )
    return aligned


def align_scenario_overlay(
    reference_overlay: Mapping[str, Any],
    target_overlay: Mapping[str, Any],
) -> Dict[str, Any]:
    """Align overlay controls without replacing target scenario identity/PV data."""
    reference = _require_mapping(reference_overlay, "reference_overlay")
    target = _require_mapping(target_overlay, "target_overlay")
    aligned = deepcopy(reference)
    _restore_keys(aligned, target, OVERLAY_IDENTITY_KEYS)

    reference_cost = _require_mapping(reference.get("cost_coefficients") or {}, "reference cost_coefficients")
    target_cost = _require_mapping(target.get("cost_coefficients") or {}, "target cost_coefficients")
    aligned_cost = deepcopy(reference_cost)
    _restore_keys(aligned_cost, target_cost, WEATHER_INPUT_OVERLAY_COST_KEYS)
    aligned["cost_coefficients"] = aligned_cost
    aligned["depot_energy_assets"] = _align_asset_collection(
        reference.get("depot_energy_assets"),
        target.get("depot_energy_assets"),
    )
    return aligned


def comparison_mismatches(
    reference_config: Mapping[str, Any],
    target_config: Mapping[str, Any],
    *,
    config_label: str,
) -> list[str]:
    """Return control-variable paths that differ from the reference case."""
    _validate_config_label(config_label)
    return [
        path
        for path in _different_paths(reference_config, target_config, config_label)
        if not _is_target_preserved_path(path, config_label)
    ]


def validate_weather_case_alignment(
    reference_config: Mapping[str, Any],
    original_target_config: Mapping[str, Any],
    aligned_target_config: Mapping[str, Any],
    *,
    config_label: str,
) -> None:
    """Verify that controls match reference and weather inputs remain target-owned.

    This verification intentionally compares three independently held payloads:
    reference, original target, and aligned target.  A weather/provenance field
    that is not in the explicit manifest is rejected instead of silently being
    treated as a model control.
    """
    _validate_config_label(config_label)
    if config_label == "simulation_config":
        _validate_time_axis_and_pv_slots(reference_config, original_target_config)
    unclassified = _unclassified_weather_paths(
        _different_paths(reference_config, original_target_config, config_label),
        config_label,
    )
    if unclassified:
        raise ValueError(
            "Unclassified weather/provenance differences: " + ", ".join(unclassified)
        )
    remaining_controls = comparison_mismatches(
        reference_config,
        aligned_target_config,
        config_label=config_label,
    )
    if remaining_controls:
        raise ValueError(
            "Alignment left control differences: " + ", ".join(remaining_controls)
        )
    changed_weather_inputs = [
        path
        for path in _different_paths(original_target_config, aligned_target_config, config_label)
        if _is_target_preserved_path(path, config_label)
    ]
    if changed_weather_inputs:
        raise ValueError(
            "Alignment changed target weather inputs: " + ", ".join(changed_weather_inputs)
        )


def _align_asset_collection(reference_assets: Any, target_assets: Any) -> Any:
    if isinstance(reference_assets, list) and isinstance(target_assets, list):
        reference_by_depot = _assets_by_depot(reference_assets)
        target_by_depot = _assets_by_depot(target_assets)
        _require_matching_depots(reference_by_depot, target_by_depot)
        return [
            _align_asset(reference_by_depot[str(asset["depot_id"])], asset)
            for asset in target_assets
        ]
    if isinstance(reference_assets, Mapping) and isinstance(target_assets, Mapping):
        reference_by_depot = {str(key): _require_mapping(value, f"reference asset {key}") for key, value in reference_assets.items()}
        target_by_depot = {str(key): _require_mapping(value, f"target asset {key}") for key, value in target_assets.items()}
        _require_matching_depots(reference_by_depot, target_by_depot)
        return {
            depot_id: _align_asset(reference_by_depot[depot_id], target_by_depot[depot_id])
            for depot_id in target_by_depot
        }
    raise ValueError("Reference and target depot_energy_assets must both be lists or mappings")


def _align_asset(reference_asset: Mapping[str, Any], target_asset: Mapping[str, Any]) -> Dict[str, Any]:
    aligned = deepcopy(dict(reference_asset))
    _restore_keys(aligned, target_asset, WEATHER_INPUT_ASSET_KEYS)
    return aligned


def _validate_time_axis_and_pv_slots(
    reference_config: Mapping[str, Any], target_config: Mapping[str, Any]
) -> None:
    reference = _require_mapping(reference_config, "reference_config")
    target = _require_mapping(target_config, "target_config")
    differences = [
        key
        for key in sorted(TIME_AXIS_KEYS)
        if reference.get(key) != target.get(key)
    ]
    reference_timestep = _timestep_minutes(reference, "reference_config")
    target_timestep = _timestep_minutes(target, "target_config")
    if reference_timestep != target_timestep:
        differences.append("timestep_min")
    if differences:
        raise ValueError(
            "Weather comparison requires identical time-axis controls: "
            + ", ".join(differences)
        )
    expected_slots = 24 * 60 // reference_timestep
    for label, config in (("reference", reference), ("target", target)):
        _validate_asset_slots(
            config.get("depot_energy_assets"),
            expected_slots=expected_slots,
            label=label,
        )


def _timestep_minutes(config: Mapping[str, Any], label: str) -> int:
    values = [
        config.get(key)
        for key in ("timestep_min", "time_step_min")
        if config.get(key) is not None
    ]
    if not values:
        raise ValueError(f"{label} requires timestep_min or time_step_min")
    normalized = {int(value) for value in values}
    if len(normalized) != 1 or next(iter(normalized)) <= 0:
        raise ValueError(f"{label} has inconsistent timestep controls")
    timestep = next(iter(normalized))
    if 24 * 60 % timestep != 0:
        raise ValueError(f"{label} timestep must evenly divide one day")
    return timestep


def _validate_asset_slots(assets: Any, *, expected_slots: int, label: str) -> None:
    for asset in _iter_assets(assets, label):
        if not bool(asset.get("pv_enabled", False)):
            continue
        _validate_slot_series(
            asset.get("pv_generation_kwh_by_slot"),
            expected_slots=expected_slots,
            label=f"{label} {asset.get('depot_id', 'asset')} pv_generation_kwh_by_slot",
            required=True,
        )
        _validate_slot_series(
            asset.get("capacity_factor_by_slot"),
            expected_slots=expected_slots,
            label=f"{label} {asset.get('depot_id', 'asset')} capacity_factor_by_slot",
            required=False,
        )
        for daily_entry in list(asset.get("pv_generation_kwh_by_date") or []):
            entry = _require_mapping(daily_entry, f"{label} daily PV entry")
            _validate_slot_series(
                entry.get("pv_generation_kwh_by_slot"),
                expected_slots=expected_slots,
                label=f"{label} daily pv_generation_kwh_by_slot",
                required=True,
            )
        for daily_entry in list(asset.get("pv_capacity_factor_by_date") or []):
            entry = _require_mapping(daily_entry, f"{label} daily capacity factor entry")
            _validate_slot_series(
                entry.get("capacity_factor_by_slot"),
                expected_slots=expected_slots,
                label=f"{label} daily capacity_factor_by_slot",
                required=True,
            )


def _iter_assets(assets: Any, label: str) -> Iterable[Dict[str, Any]]:
    if isinstance(assets, list):
        return [_require_mapping(asset, f"{label} depot energy asset") for asset in assets]
    if isinstance(assets, Mapping):
        return [_require_mapping(asset, f"{label} depot energy asset") for asset in assets.values()]
    raise ValueError(f"{label} depot_energy_assets must be a list or mapping")


def _validate_slot_series(
    values: Any,
    *,
    expected_slots: int,
    label: str,
    required: bool,
) -> None:
    if values is None or values == []:
        if required:
            raise ValueError(f"{label} must contain {expected_slots} slot values")
        return
    if not isinstance(values, list) or len(values) != expected_slots:
        actual = len(values) if isinstance(values, list) else "non-list"
        raise ValueError(f"{label} must contain {expected_slots} slot values, got {actual}")


def _assets_by_depot(assets: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    by_depot: Dict[str, Dict[str, Any]] = {}
    for asset in assets:
        mapping = _require_mapping(asset, "depot energy asset")
        depot_id = str(mapping.get("depot_id") or "").strip()
        if not depot_id or depot_id in by_depot:
            raise ValueError("depot_energy_assets must have unique, non-empty depot_id values")
        by_depot[depot_id] = mapping
    return by_depot


def _require_matching_depots(
    reference_assets: Mapping[str, Any], target_assets: Mapping[str, Any]
) -> None:
    if set(reference_assets) != set(target_assets):
        raise ValueError("Reference and target depot_energy_assets must cover the same depots")


def _restore_keys(destination: Dict[str, Any], source: Mapping[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        if key in source:
            destination[key] = deepcopy(source[key])
        else:
            destination.pop(key, None)


def _validate_config_label(config_label: str) -> None:
    if config_label not in {"simulation_config", "scenario_overlay"}:
        raise ValueError(f"Unsupported comparison config label: {config_label}")


def _is_target_preserved_path(path: str, config_label: str) -> bool:
    if config_label == "simulation_config":
        if _path_matches_keys(path, "simulation_config", WEATHER_INPUT_SIMULATION_KEYS):
            return True
    elif config_label == "scenario_overlay":
        if _path_matches_keys(path, "scenario_overlay", OVERLAY_IDENTITY_KEYS):
            return True
        if _path_matches_keys(
            path,
            "scenario_overlay.cost_coefficients",
            WEATHER_INPUT_OVERLAY_COST_KEYS,
        ):
            return True
    return ".depot_energy_assets" in path and any(
        f".{key}" in path for key in WEATHER_INPUT_ASSET_KEYS
    )


def _path_matches_keys(path: str, prefix: str, keys: Iterable[str]) -> bool:
    return any(
        path == f"{prefix}.{key}"
        or path.startswith(f"{prefix}.{key}.")
        or path.startswith(f"{prefix}.{key}[")
        for key in keys
    )


def _unclassified_weather_paths(paths: Iterable[str], config_label: str) -> list[str]:
    classified = []
    for path in paths:
        leaf = path.rsplit(".", maxsplit=1)[-1].split("[", maxsplit=1)[0].lower()
        looks_weather_specific = any(
            token in leaf for token in ("weather", "forecast", "solcast")
        )
        if looks_weather_specific and not _is_target_preserved_path(path, config_label):
            classified.append(path)
    return classified


def _require_mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return dict(value)


def _different_paths(expected: Any, actual: Any, prefix: str) -> list[str]:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        paths: list[str] = []
        for key in sorted(set(expected).union(actual)):
            paths.extend(_different_paths(expected.get(key), actual.get(key), f"{prefix}.{key}"))
        return paths
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [prefix]
        paths: list[str] = []
        for index, (expected_value, actual_value) in enumerate(zip(expected, actual)):
            paths.extend(_different_paths(expected_value, actual_value, f"{prefix}[{index}]"))
        return paths
    return [] if expected == actual else [prefix]
