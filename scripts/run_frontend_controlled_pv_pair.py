"""Run a controlled same-service-date PV pair through the frontend BFF HTTP API.

This runner deliberately has no optimization-domain imports.  It submits the
same Prepare and run-optimization endpoints used by the frontend, polls the
public job endpoint, preserves the exact HTTP JSON payloads, and builds a
portable evidence bundle from the completed run directories.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping
from urllib import error, request
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DERIVED_PV_PROFILE_DIR = REPO_ROOT / "data" / "derived" / "pv_profiles"
TERMINAL_JOB_STATES = {"completed", "failed"}
FORBIDDEN_PREPARED_INPUT_IDS = {
    "prepared-a7dbfaef10f571d7-e6406a7fd75ec751-9dfce7cb",
    "prepared-6bcba1be5c1141c8-0b337aa1f091e729-9dfce7cb",
}
EXPECTED_PV_KWH = {
    "sunny": 614.709375,
    "rain": 101.1143,
}
REFERENCE_PV_CAPACITY_KW = 101.5
POWERTRAIN_ELECTRIC = {"BEV", "PHEV", "FCEV"}
TARGET_ROUTE_IDS_BY_DEPOT = {
    # Canonical 16-variant Tsurumaki scope recovered identically from both
    # diagnostic prepared inputs named in the execution instruction.  The
    # inputs themselves are never executed or copied into formal evidence.
    "tsurumaki": (
        "odpt-route-0b2ab9e74da1",
        "odpt-route-206aa2ef5f3a",
        "odpt-route-3da308a5063b",
        "odpt-route-4109a31659bc",
        "odpt-route-495b9472e61b",
        "odpt-route-5274690b4073",
        "odpt-route-599baa9cb2fb",
        "odpt-route-733dcb7dff82",
        "odpt-route-844516ff5c40",
        "odpt-route-a66f2ed85ff9",
        "odpt-route-a6b5e7bf98f7",
        "odpt-route-af678f3a3006",
        "odpt-route-d398fae40154",
        "odpt-route-e046125fefb1",
        "odpt-route-e3a3088fd8ba",
        "odpt-route-fb12ae43f5b0",
    ),
}


def _expected_pv_kwh_for_capacity(case_name: str, capacity_kw: float) -> float:
    return round(
        EXPECTED_PV_KWH[case_name]
        * float(capacity_kw)
        / REFERENCE_PV_CAPACITY_KW,
        6,
    )


def _validate_pv_capacity_override_request(
    *,
    pv_capacity_kw: float | None,
    allow_frontend_pv_capacity_override: bool,
) -> None:
    """Reject accidental replacement of a frontend rated-output selection."""

    if pv_capacity_kw is None:
        return
    if not math.isfinite(pv_capacity_kw) or pv_capacity_kw <= 0.0:
        raise ValueError("--pv-capacity-kw must be a positive finite kW value")
    if not allow_frontend_pv_capacity_override:
        raise ValueError(
            "--pv-capacity-kw replaces the frontend PV rated output. Omit it "
            "to use the saved frontend value, or add "
            "--allow-frontend-pv-capacity-override for an intentional "
            "capacity sensitivity."
        )


CONTROLLED_COST_COMPONENT_FLAGS = {
    "vehicle_fixed_cost": False,
    "vehicle_usage_cost": True,
    "driver_cost": False,
    "electricity_cost": True,
    "fuel_cost": True,
    "demand_charge_cost": True,
    "co2_cost": True,
    "unserved_penalty": True,
    "switch_cost": True,
    "battery_degradation_cost": True,
    "deviation_cost": False,
    "contract_overage_penalty": True,
    "charge_session_start_penalty": False,
    "slot_concurrency_penalty": False,
    "early_charge_penalty": False,
    "soc_upper_buffer_penalty": False,
    "final_soc_target_penalty": False,
    "opportunistic_topup_deficit_penalty": False,
    "grid_to_bus_priority_penalty": True,
    "grid_to_bess_priority_penalty": True,
}


def _build_uniform_tariff_settings(
    *,
    grid_energy_price_yen_per_kwh: float | None,
    demand_charge_yen_per_kw: float | None,
) -> dict[str, Any]:
    """Return an explicit all-day tariff override or no override.

    A flat-price field alone is insufficient when a scenario already has TOU
    bands, because canonical price construction gives those bands precedence.
    The one 00:00--24:00 band therefore deliberately replaces any inherited
    TOU schedule while retaining the flat-rate value as explicit provenance.
    """

    if (
        grid_energy_price_yen_per_kwh is None
        and demand_charge_yen_per_kw is None
    ):
        return {}
    if (
        grid_energy_price_yen_per_kwh is None
        or demand_charge_yen_per_kw is None
    ):
        raise ValueError(
            "A controlled tariff requires both grid energy price and "
            "demand-charge rate."
        )
    grid_energy_price = float(grid_energy_price_yen_per_kwh)
    demand_charge = float(demand_charge_yen_per_kw)
    for label, value in (
        ("grid energy price", grid_energy_price),
        ("demand-charge rate", demand_charge),
    ):
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(
                f"Controlled {label} must be a finite non-negative value."
            )
    return {
        "grid_flat_price_per_kwh": grid_energy_price,
        "demand_charge_cost_per_kw": demand_charge,
        "tou_pricing": [
            {
                "start_hour": 0,
                "end_hour": 24,
                "price_per_kwh": grid_energy_price,
            }
        ],
    }


def _uniform_tariff_condition(
    *,
    grid_energy_price_yen_per_kwh: float | None,
    demand_charge_yen_per_kw: float | None,
) -> dict[str, Any]:
    """Normalize the requested tariff condition for evidence artifacts."""

    settings = _build_uniform_tariff_settings(
        grid_energy_price_yen_per_kwh=grid_energy_price_yen_per_kwh,
        demand_charge_yen_per_kw=demand_charge_yen_per_kw,
    )
    return {
        "override_requested": bool(settings),
        "grid_energy_price_yen_per_kwh": settings.get(
            "grid_flat_price_per_kwh"
        ),
        "demand_charge_yen_per_kw": settings.get(
            "demand_charge_cost_per_kw"
        ),
        "tou_pricing": settings.get("tou_pricing") or [],
        "semantics": (
            "The demand-charge rate is the model's basic/contract-power "
            "charge coefficient; zero disables that cost term without "
            "changing physical import limits."
            if settings
            else "Use the scenario's persisted tariff without an override."
        ),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return dict(loaded)


def _read_json_optional(path: Path) -> dict[str, Any]:
    return _read_json(path) if path.is_file() else {}


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def _assert_clean_frozen_repository() -> str:
    status = _git("status", "--porcelain")
    if status:
        raise RuntimeError(
            "Formal pair execution requires a clean worktree; commit or "
            "remove intentional changes first.\n" + status
        )
    sha = _git("rev-parse", "HEAD")
    if not sha:
        raise RuntimeError("Formal pair execution requires a non-empty Git SHA")
    return sha


def build_prepare_payload(
    *,
    depot_id: str,
    service_id: str,
    service_date: str,
    pv_source_date: str,
    comparison_role: str,
    vehicle_usage_cost_semantics: str = "unclassified",
    grid_energy_price_yen_per_kwh: float | None = None,
    demand_charge_yen_per_kw: float | None = None,
) -> dict[str, Any]:
    """Build the explicit frontend Prepare payload for one controlled case."""

    if comparison_role not in {"baseline", "pv_curve_counterfactual"}:
        raise ValueError(f"Unsupported comparison role: {comparison_role}")
    route_ids = TARGET_ROUTE_IDS_BY_DEPOT.get(depot_id)
    if not route_ids:
        raise ValueError(
            f"No controlled route-scope contract exists for depot {depot_id}"
        )
    tariff_settings = _build_uniform_tariff_settings(
        grid_energy_price_yen_per_kwh=grid_energy_price_yen_per_kwh,
        demand_charge_yen_per_kw=demand_charge_yen_per_kw,
    )
    tariff_note = ""
    if tariff_settings:
        tariff_note = (
            " Grid purchase is fixed at "
            f"{tariff_settings['grid_flat_price_per_kwh']:g} JPY/kWh for "
            "every clock slot and the demand-charge rate is "
            f"{tariff_settings['demand_charge_cost_per_kw']:g} JPY/kW."
        )
    return {
        "selected_depot_ids": [depot_id],
        "selected_route_ids": list(route_ids),
        "day_type": service_id,
        "service_date": service_date,
        "service_dates": [service_date],
        "include_short_turn": True,
        "include_depot_moves": True,
        "include_deadhead": True,
        "allow_intra_depot_route_swap": False,
        "allow_inter_depot_swap": False,
        "simulation_settings": {
            "use_selected_depot_vehicle_inventory": True,
            "use_selected_depot_charger_inventory": True,
            # These non-PV controls reproduce the explicitly materialized
            # selected-depot fleet state shared by the two diagnostic inputs.
            # Per-vehicle inventory SOC remains authoritative; the percentages
            # below define common bounds/terminal and ICE initialization only.
            "initial_soc": 0.8,
            "initial_soc_percent": 0.8,
            "soc_min": 0.2,
            "soc_max": 0.9,
            "final_soc_floor_percent": 20.0,
            "final_soc_target_percent": 80.0,
            "final_soc_target_tolerance_percent": 20.0,
            "initial_ice_fuel_percent": 100.0,
            "min_ice_fuel_percent": 10.0,
            "max_ice_fuel_percent": 90.0,
            "default_ice_tank_capacity_l": 300.0,
            "disable_vehicle_acquisition_cost": True,
            "enable_vehicle_cost": False,
            "enable_driver_cost": False,
            "enable_other_cost": False,
            "cost_component_flags": dict(
                CONTROLLED_COST_COMPONENT_FLAGS
            ),
            "vehicle_usage_cost_semantics": vehicle_usage_cost_semantics,
            **tariff_settings,
            "solver_mode": "mode_milp_only",
            "objective_mode": "total_cost",
            "fixed_route_band_mode": True,
            "allow_partial_service": False,
            "milp_max_successors_per_trip": None,
            "time_limit_seconds": 1800,
            "mip_gap": 0.1,
            "include_deadhead": True,
            "service_date": service_date,
            "service_dates": [service_date],
            "planning_days": 1,
            "operation_time_window_enabled": False,
            "start_time": "00:00",
            "end_time": "23:59",
            "planning_horizon_hours": 24.0,
            "time_step_min": 60,
            "timestep_min": 60,
            "pv_profile_id": f"{depot_id}_{pv_source_date}_60min",
            "weather_mode": "actual_date_profile",
            "comparison_type": "same_service_date_pv_counterfactual",
            "comparison_role": comparison_role,
            "counterfactual_pv_source_date": pv_source_date,
            "allow_fixed_weekday_timetable_pv_counterfactual": (
                comparison_role == "pv_curve_counterfactual"
            ),
            "enable_weather_operation_policy": False,
            "co2_price_source": "manual",
            "solcast_typical_weather_class": "auto",
            "random_seed": 42,
            "experiment_method": (
                "same_service_date_pv_counterfactual_frontend_http"
            ),
            "experiment_notes": (
                f"Same {service_date} weekday service controls; only the "
                "separately fingerprinted PV curve may differ."
                + tariff_note
            ),
        },
    }


def build_optimization_payload(
    prepared_input_id: str,
    *,
    experiment_case: str = "phase3_baseline",
    actual_cost_upper_bound_jpy: float | None = None,
    actual_cost_upper_bound_delta_ratio: float | None = None,
) -> dict[str, Any]:
    """Build the identical frontend optimization request for either case."""

    payload = {
        "mode": "mode_milp_only",
        "research_run": True,
        "time_step_min": 60,
        "timestep_min": 60,
        "time_limit_seconds": 1800,
        "stage1_time_limit_seconds": 1500,
        "stage2_time_limit_seconds": 300,
        "stage1_best_obj_stop_enabled": False,
        # One incumbent plus up to twenty alternatives supports the mandatory
        # composition and same-assignment audit without introducing a
        # weather-specific bias.
        "stage1_stage2_candidate_limit": 21,
        "stage1_composition_search_radius": 2,
        "gurobi_threads": 1,
        "run_profile": "day_ahead_and_hourly_rolling",
        "run_hourly_rolling": True,
        "rolling_execution_minutes": 60,
        "mip_gap": 0.1,
        "random_seed": 42,
        "prepared_input_id": prepared_input_id,
        "service_id": "WEEKDAY",
        "depot_id": "tsurumaki",
        "rebuild_dispatch": False,
        "force_reprepare": False,
        "use_existing_duties": False,
        "alns_iterations": 500,
        "no_improvement_limit": 100,
        "destroy_fraction": 0.25,
        "weatherProxyForecastPath": None,
        "enableWeatherOperationPolicy": False,
        "require_all_available_bevs": False,
    }
    if experiment_case == "phase3_bev_frontier":
        payload.update(
            {
                "mode": "phase3_two_stage",
                "time_limit_seconds": 3600,
                "stage1_time_limit_seconds": 3000,
                "stage2_time_limit_seconds": 600,
                "stage1_stage2_candidate_limit": 22,
                "stage1_composition_search_radius": 0,
                "stage1_bev_frontier_enabled": True,
                "stage1_bev_frontier_min_count": 15,
                "stage1_bev_frontier_max_count": 35,
                "stage1_bev_frontier_target_time_limit_seconds": 120,
            }
        )
    elif experiment_case == "phase4_integrated_actual_cost":
        payload.update(
            {
                "mode": "phase4_integrated",
                "time_limit_seconds": 3600,
                "stage1_time_limit_seconds": None,
                "stage2_time_limit_seconds": None,
                "stage1_stage2_candidate_limit": 1,
                "stage1_composition_search_radius": 0,
                # Five percent prevents a merely feasible Phase 3 seed near
                # the 640,000 JPY vehicle-day lower bound from terminating the
                # integrated solve immediately at the former 10% threshold.
                "mip_gap": 0.05,
                "integrated_actual_cost_objective": True,
            }
        )
    elif experiment_case in {
        "phase4_maximum_ev_utilization",
        "phase4_cost_constrained_ev_utilization",
    }:
        if (
            experiment_case == "phase4_cost_constrained_ev_utilization"
            and actual_cost_upper_bound_jpy is None
        ):
            raise ValueError(
                "phase4_cost_constrained_ev_utilization requires an absolute "
                "canonical actual-cost upper bound"
            )
        payload.update(
            {
                "mode": "phase4_integrated",
                "time_limit_seconds": 3600,
                "stage1_time_limit_seconds": None,
                "stage2_time_limit_seconds": None,
                "stage1_stage2_candidate_limit": 1,
                "stage1_composition_search_radius": 0,
                "mip_gap": 0.05,
                "integrated_actual_cost_objective": False,
                "integrated_ev_utilization_mode": (
                    "minimum_ice_fuel_lexicographic"
                ),
                "integrated_actual_cost_upper_bound_jpy": (
                    actual_cost_upper_bound_jpy
                ),
                "integrated_actual_cost_upper_bound_delta_ratio": (
                    actual_cost_upper_bound_delta_ratio
                ),
            }
        )
    elif experiment_case != "phase3_baseline":
        raise ValueError(
            f"Unsupported optimization experiment case: {experiment_case}"
        )
    return payload


class HttpJsonClient:
    """Minimal JSON client that retains the exact response body."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float = 120.0,
    ) -> tuple[dict[str, Any], str]:
        encoded = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        http_request = request.Request(
            f"{self.base_url}{path}",
            data=encoded,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(
                http_request,
                timeout=timeout_seconds,
            ) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{method} {path} returned HTTP {exc.code}: {raw}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"{method} {path} failed: {exc}") from exc
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise ValueError(f"{method} {path} did not return a JSON object")
        return dict(loaded), raw


def _required_positive_number(
    payload: Mapping[str, Any],
    *keys: str,
    label: str,
) -> float:
    """Read one finite positive numeric field without silently defaulting it."""

    for key in keys:
        value = _number(payload.get(key))
        if value is not None and math.isfinite(value) and value > 0.0:
            return float(value)
    joined = "/".join(keys)
    raise ValueError(
        f"Frontend depot asset has no finite positive {label} ({joined})."
    )


def _load_derived_pv_profile(
    *,
    depot_id: str,
    pv_source_date: str,
    timestep_min: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate the date-specific, scale-free PV source profile.

    The profile's capacity factors come from the repository's generated
    Solcast-derived source.  Installed capacity remains a scenario control and
    is reconstructed from the frontend depot-area settings below; this avoids
    borrowing the source profile generator's nominal capacity for a different
    depot installation.
    """

    profile_path = (
        DERIVED_PV_PROFILE_DIR
        / f"{depot_id}_{pv_source_date}_{int(timestep_min)}min.json"
    )
    if not profile_path.is_file():
        raise FileNotFoundError(
            "Date-specific derived PV profile is missing: "
            f"{profile_path}"
        )
    profile_bytes = profile_path.read_bytes()
    profile = _read_json(profile_path)
    if str(profile.get("depot_id") or "") != depot_id:
        raise ValueError(
            f"PV profile depot mismatch: expected {depot_id}, got "
            f"{profile.get('depot_id')!r}"
        )
    if str(profile.get("date") or "") != pv_source_date:
        raise ValueError(
            f"PV profile date mismatch: expected {pv_source_date}, got "
            f"{profile.get('date')!r}"
        )
    if int(profile.get("slot_minutes") or 0) != int(timestep_min):
        raise ValueError(
            "PV profile timestep mismatch: expected "
            f"{timestep_min}, got {profile.get('slot_minutes')!r}"
        )
    expected_slot_count = (24 * 60) // int(timestep_min)
    raw_factors = list(profile.get("capacity_factor_by_slot") or ())
    if len(raw_factors) != expected_slot_count:
        raise ValueError(
            "PV profile slot count mismatch: expected "
            f"{expected_slot_count}, got {len(raw_factors)}"
        )
    factors: list[float] = []
    for slot_index, raw_factor in enumerate(raw_factors):
        factor = _number(raw_factor)
        if factor is None or not math.isfinite(factor) or not 0.0 <= factor <= 1.0:
            raise ValueError(
                "PV profile capacity factor must be finite within [0, 1]: "
                f"slot {slot_index}={raw_factor!r}"
            )
        factors.append(float(factor))
    normalized = dict(profile)
    normalized["capacity_factor_by_slot"] = factors
    provenance = {
        "schema_version": "controlled_pv_profile_source_v1",
        "profile_path": str(profile_path.resolve()),
        "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "depot_id": depot_id,
        "pv_source_date": pv_source_date,
        "timestep_min": int(timestep_min),
        "profile_nominal_capacity_kw": _number(profile.get("capacity_kw")),
        "capacity_factor_by_slot": factors,
    }
    return normalized, provenance


def _frontend_depot_asset(
    bootstrap: Mapping[str, Any],
    *,
    depot_id: str,
) -> dict[str, Any]:
    """Extract exactly one existing depot asset from the frontend payload."""

    defaults = bootstrap.get("builderDefaults")
    if not isinstance(defaults, Mapping):
        raise ValueError("Frontend editor-bootstrap omitted builderDefaults")
    raw_assets = defaults.get("depotEnergyAssets")
    if isinstance(raw_assets, Mapping):
        iterable = [
            dict(value, depot_id=str(key))
            for key, value in raw_assets.items()
            if isinstance(value, Mapping)
        ]
    else:
        iterable = [
            dict(value)
            for value in list(raw_assets or ())
            if isinstance(value, Mapping)
        ]
    matches = [
        asset
        for asset in iterable
        if str(asset.get("depot_id") or asset.get("depotId") or "")
        == depot_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "Frontend editor-bootstrap must contain exactly one depot energy "
            f"asset for {depot_id}; found {len(matches)}"
        )
    return dict(matches[0])


def _build_controlled_pv_asset(
    *,
    frontend_asset: Mapping[str, Any],
    profile: Mapping[str, Any],
    profile_provenance: Mapping[str, Any],
    pv_capacity_kw: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replace only the selected PV curve in a frontend depot asset.

    BESS and every other non-PV field are copied verbatim from the frontend
    builder defaults.  An explicit rated output takes precedence; otherwise a
    frontend manual override is retained, with area-derived capacity used only
    for legacy assets that have no explicit rated-output contract.
    """

    depot_id = str(profile_provenance.get("depot_id") or "")
    pv_source_date = str(profile_provenance.get("pv_source_date") or "")
    timestep_min = int(profile_provenance.get("timestep_min") or 0)
    if not depot_id or not pv_source_date or timestep_min <= 0:
        raise ValueError("PV source provenance is incomplete")
    asset_depot_id = str(
        frontend_asset.get("depot_id") or frontend_asset.get("depotId") or ""
    )
    if asset_depot_id != depot_id:
        raise ValueError(
            f"Frontend asset depot mismatch: expected {depot_id}, got "
            f"{asset_depot_id!r}"
        )

    depot_area_m2 = _number(
        frontend_asset.get("depot_area_m2")
        if "depot_area_m2" in frontend_asset
        else frontend_asset.get("depotAreaM2")
    )
    usable_area_ratio = _required_positive_number(
        frontend_asset,
        "usable_area_ratio",
        "usableAreaRatio",
        label="usable-area ratio",
    )
    panel_power_density_kw_m2 = _required_positive_number(
        frontend_asset,
        "panel_power_density_kw_m2",
        "panelPowerDensityKwM2",
        label="panel-power density",
    )
    area_derived_capacity_kw = (
        round(
            depot_area_m2 * usable_area_ratio * panel_power_density_kw_m2,
            6,
        )
        if depot_area_m2 is not None and depot_area_m2 > 0.0
        else None
    )
    frontend_capacity_kw = _number(
        frontend_asset.get("pv_capacity_kw")
        if "pv_capacity_kw" in frontend_asset
        else frontend_asset.get("pvCapacityKw")
    )
    frontend_manual_override = bool(
        frontend_asset.get(
            "pv_capacity_kw_manual_override",
            frontend_asset.get("pvCapacityKwManualOverride", False),
        )
    )
    if pv_capacity_kw is not None:
        selected_capacity_kw = float(pv_capacity_kw)
        capacity_source = "runner_argument"
    elif frontend_manual_override and frontend_capacity_kw is not None:
        selected_capacity_kw = float(frontend_capacity_kw)
        capacity_source = "frontend_rated_output"
    elif area_derived_capacity_kw is not None:
        selected_capacity_kw = float(area_derived_capacity_kw)
        capacity_source = "legacy_depot_area_estimate"
    else:
        raise ValueError(
            "Controlled PV asset requires an explicit rated output or a "
            "positive legacy depot-area estimate"
        )
    if not math.isfinite(selected_capacity_kw) or selected_capacity_kw <= 0.0:
        raise ValueError("PV rated output must be a positive finite kW value")
    selected_capacity_kw = round(selected_capacity_kw, 6)
    estimated_installable_area_m2 = round(
        selected_capacity_kw / panel_power_density_kw_m2,
        6,
    )
    estimated_depot_area_m2 = round(
        estimated_installable_area_m2 / usable_area_ratio,
        6,
    )

    factors = list(profile.get("capacity_factor_by_slot") or ())
    expected_slot_count = (24 * 60) // timestep_min
    if len(factors) != expected_slot_count:
        raise ValueError(
            "PV profile factor count does not match the requested timestep"
        )
    slot_h = float(timestep_min) / 60.0
    generation = [
        round(selected_capacity_kw * float(factor) * slot_h, 6)
        for factor in factors
    ]
    profile_id = f"{depot_id}_{pv_source_date}_{timestep_min}min"
    asset = dict(frontend_asset)
    asset.update(
        {
            "depot_id": depot_id,
            "pv_enabled": True,
            "pv_capacity_kw": selected_capacity_kw,
            "pv_capacity_kw_manual_override": True,
            "pv_capacity_input_mode": "rated_output_manual",
            "estimated_installable_area_m2": estimated_installable_area_m2,
            "estimated_depot_area_from_pv_capacity_m2": estimated_depot_area_m2,
            "derived_pv_capacity_kw": selected_capacity_kw,
            "pv_case_id": profile_id,
            "pv_profile_source": "derived_daily",
            "pv_source_type": "solcast_daily",
            "pv_source_date": pv_source_date,
            "pv_profile_dates": [pv_source_date],
            "pv_slot_minutes": timestep_min,
            "capacity_factor_by_slot": factors,
            "pv_generation_kwh_by_slot": generation,
            "pv_generation_kwh_by_date": [
                {
                    "date": pv_source_date,
                    "slot_minutes": timestep_min,
                    "pv_generation_kwh_by_slot": generation,
                }
            ],
            "pv_capacity_factor_by_date": [
                {
                    "date": pv_source_date,
                    "slot_minutes": timestep_min,
                    "capacity_factor_by_slot": factors,
                }
            ],
        }
    )
    evidence = {
        "schema_version": "controlled_pv_asset_replacement_v2",
        **dict(profile_provenance),
        "frontend_asset_pv_capacity_kw_before": _number(
            frontend_asset.get("pv_capacity_kw")
            if "pv_capacity_kw" in frontend_asset
            else frontend_asset.get("pvCapacityKw")
        ),
        "frontend_asset_pv_manual_override_before": frontend_manual_override,
        "selected_pv_capacity_kw": selected_capacity_kw,
        "selected_pv_capacity_source": capacity_source,
        "area_derived_installed_capacity_kw": area_derived_capacity_kw,
        "estimated_installable_area_m2": estimated_installable_area_m2,
        "estimated_depot_area_from_pv_capacity_m2": estimated_depot_area_m2,
        "pv_profile_id": profile_id,
        "pv_generation_kwh": round(sum(generation), 6),
        "pv_generation_kwh_by_slot": generation,
        "non_pv_asset_hash_before": _canonical_hash(
            {
                key: value
                for key, value in frontend_asset.items()
                if not key.startswith("pv_")
                and not key.startswith("pv")
                and key
                not in {
                    "capacity_factor_by_slot",
                    "capacityFactorBySlot",
                }
            }
        ),
    }
    return asset, evidence


def _attach_controlled_pv_asset_to_prepare_payload(
    *,
    client: HttpJsonClient,
    scenario_id: str,
    prepare_payload: Mapping[str, Any],
    expected_pv_kwh: float | None,
    timeout_seconds: float,
    pv_capacity_kw: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch frontend asset controls and attach one explicit PV curve to Prepare."""

    selected_depots = list(prepare_payload.get("selected_depot_ids") or ())
    if len(selected_depots) != 1:
        raise ValueError("Controlled PV Prepare requires exactly one depot")
    depot_id = str(selected_depots[0])
    settings = prepare_payload.get("simulation_settings")
    if not isinstance(settings, Mapping):
        raise ValueError("Prepare payload omitted simulation_settings")
    pv_source_date = str(settings.get("counterfactual_pv_source_date") or "")
    timestep_min = int(settings.get("time_step_min") or 0)
    if not pv_source_date or timestep_min <= 0:
        raise ValueError("Prepare payload has no PV source date/timestep")

    bootstrap, bootstrap_raw = client.request_json(
        "GET",
        f"/api/scenarios/{scenario_id}/editor-bootstrap",
        timeout_seconds=timeout_seconds,
    )
    frontend_asset = _frontend_depot_asset(bootstrap, depot_id=depot_id)
    profile, profile_provenance = _load_derived_pv_profile(
        depot_id=depot_id,
        pv_source_date=pv_source_date,
        timestep_min=timestep_min,
    )
    asset, evidence = _build_controlled_pv_asset(
        frontend_asset=frontend_asset,
        profile=profile,
        profile_provenance=profile_provenance,
        pv_capacity_kw=pv_capacity_kw,
    )
    actual_pv_kwh = _number(evidence.get("pv_generation_kwh"))
    if (
        expected_pv_kwh is not None
        and (
            actual_pv_kwh is None
            or not math.isclose(
                actual_pv_kwh,
                float(expected_pv_kwh),
                rel_tol=0.0,
                abs_tol=1.0e-6,
            )
        )
    ):
        raise RuntimeError(
            "Selected PV source does not yield the controlled expected total: "
            f"expected {expected_pv_kwh}, got {actual_pv_kwh}"
        )
    evidence["expected_pv_generation_kwh"] = (
        round(float(expected_pv_kwh), 6)
        if expected_pv_kwh is not None
        else actual_pv_kwh
    )

    attached_payload = json.loads(
        json.dumps(prepare_payload, ensure_ascii=False, allow_nan=False)
    )
    attached_payload["simulation_settings"]["depot_energy_assets"] = [asset]
    context = {
        "frontend_editor_bootstrap_response_raw": bootstrap_raw,
        "pv_profile_source": evidence,
        "frontend_depot_energy_asset_request": asset,
    }
    return attached_payload, context


def _write_raw_json_response(path: Path, raw: str) -> None:
    # Validate before persisting while retaining the server's exact numeric
    # tokens and response formatting.
    json.loads(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


def _poll_job(
    *,
    client: HttpJsonClient,
    job_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    log: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    started = time.monotonic()
    previous_signature: tuple[Any, ...] | None = None
    while True:
        job, raw = client.request_json(
            "GET",
            f"/api/jobs/{job_id}",
            timeout_seconds=120.0,
        )
        signature = (
            job.get("status"),
            job.get("progress"),
            job.get("message"),
            dict(job.get("metadata") or {}).get("stage"),
        )
        if signature != previous_signature:
            event = {
                "timestamp_utc": _utc_now(),
                "event": "job_progress",
                "job_id": job_id,
                "status": job.get("status"),
                "progress": job.get("progress"),
                "stage": dict(job.get("metadata") or {}).get("stage"),
                "message": job.get("message"),
            }
            log.append(event)
            print(
                "[job] "
                f"{job_id} {event['status']} {event['progress']}% "
                f"{event['stage']}: {event['message']}",
                flush=True,
            )
            previous_signature = signature
        if str(job.get("status") or "") in TERMINAL_JOB_STATES:
            return job, raw
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError(
                f"Job {job_id} did not reach a terminal state within "
                f"{timeout_seconds} seconds"
            )
        time.sleep(max(poll_interval_seconds, 0.1))


def _copy_run_contents(run_dir: Path, case_dir: Path) -> None:
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Frontend run directory is missing: {run_dir}")
    shutil.copytree(run_dir, case_dir, dirs_exist_ok=True)


def _execute_case(
    *,
    name: str,
    scenario_id: str,
    prepare_payload: dict[str, Any],
    client: HttpJsonClient,
    output_dir: Path,
    timeout_seconds: float,
    poll_interval_seconds: float,
    frozen_sha: str,
    log: list[dict[str, Any]],
    pv_asset_context: Mapping[str, Any] | None = None,
    optimization_experiment_case: str = "phase3_baseline",
    actual_cost_upper_bound_jpy: float | None = None,
    actual_cost_upper_bound_delta_ratio: float | None = None,
) -> dict[str, Any]:
    case_dir = output_dir / name
    case_dir.mkdir(parents=True, exist_ok=False)
    if pv_asset_context is not None:
        bootstrap_raw = str(
            pv_asset_context.get("frontend_editor_bootstrap_response_raw")
            or ""
        )
        if not bootstrap_raw:
            raise ValueError("Controlled PV case lacks editor-bootstrap evidence")
        _write_raw_json_response(
            case_dir / "frontend_editor_bootstrap_response.json",
            bootstrap_raw,
        )
        _write_json(
            case_dir / "pv_profile_source.json",
            dict(pv_asset_context.get("pv_profile_source") or {}),
        )
        _write_json(
            case_dir / "frontend_depot_energy_asset_request.json",
            dict(
                pv_asset_context.get("frontend_depot_energy_asset_request")
                or {}
            ),
        )
    _write_json(case_dir / "frontend_prepare_request.json", prepare_payload)
    prepare_response, prepare_raw = client.request_json(
        "POST",
        f"/api/scenarios/{scenario_id}/simulation/prepare",
        prepare_payload,
        timeout_seconds=timeout_seconds,
    )
    _write_raw_json_response(
        case_dir / "frontend_prepare_response.json",
        prepare_raw,
    )
    if prepare_response.get("ready") is not True:
        raise RuntimeError(
            f"{name} Prepare was not ready: "
            f"{json.dumps(prepare_response, ensure_ascii=False)}"
        )
    requested_route_count = len(
        list(prepare_payload.get("selected_route_ids") or ())
    )
    if (
        requested_route_count <= 0
        or int(prepare_response.get("routeCount") or 0)
        != requested_route_count
    ):
        raise RuntimeError(
            f"{name} Prepare route scope mismatch: requested "
            f"{requested_route_count}, materialized "
            f"{prepare_response.get('routeCount')}"
        )
    if int(prepare_response.get("tripCount") or 0) <= 0:
        raise RuntimeError(f"{name} Prepare materialized no trips")
    prepared_input_id = str(
        prepare_response.get("preparedInputId") or ""
    ).strip()
    if not prepared_input_id:
        raise RuntimeError(f"{name} Prepare returned an empty preparedInputId")
    if prepared_input_id in FORBIDDEN_PREPARED_INPUT_IDS:
        raise RuntimeError(
            f"{name} Prepare reused forbidden old input {prepared_input_id}"
        )

    optimization_payload = build_optimization_payload(
        prepared_input_id,
        experiment_case=optimization_experiment_case,
        actual_cost_upper_bound_jpy=actual_cost_upper_bound_jpy,
        actual_cost_upper_bound_delta_ratio=(
            actual_cost_upper_bound_delta_ratio
        ),
    )
    optimization_payload["service_id"] = str(
        prepare_payload.get("day_type") or "WEEKDAY"
    )
    optimization_payload["depot_id"] = str(
        list(prepare_payload.get("selected_depot_ids") or [""])[0]
    )
    _write_json(
        case_dir / "frontend_optimization_request.json",
        optimization_payload,
    )
    started_utc = _utc_now()
    started = time.monotonic()
    submit_response, submit_raw = client.request_json(
        "POST",
        f"/api/scenarios/{scenario_id}/run-optimization",
        optimization_payload,
        timeout_seconds=timeout_seconds,
    )
    _write_raw_json_response(
        case_dir / "frontend_optimization_submit_response.json",
        submit_raw,
    )
    job_id = str(
        submit_response.get("job_id")
        or submit_response.get("jobId")
        or ""
    ).strip()
    if not job_id:
        raise RuntimeError(
            f"{name} optimization submit did not return a job ID"
        )
    terminal, terminal_raw = _poll_job(
        client=client,
        job_id=job_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        log=log,
    )
    wall_time_sec = time.monotonic() - started
    _write_raw_json_response(
        case_dir / "frontend_job_terminal_response.json",
        terminal_raw,
    )
    metadata = dict(terminal.get("metadata") or {})
    run_dir_text = str(metadata.get("run_dir") or "").strip()
    run_dir = Path(run_dir_text) if run_dir_text else None
    if run_dir is not None and run_dir.is_dir():
        _copy_run_contents(run_dir, case_dir)

    result_response: dict[str, Any] | None = None
    if terminal.get("status") == "completed":
        result_response, result_raw = client.request_json(
            "GET",
            f"/api/scenarios/{scenario_id}/optimization",
            timeout_seconds=120.0,
        )
        _write_raw_json_response(
            case_dir / "frontend_optimization_result_response.json",
            result_raw,
        )
    http_execution_path = []
    if pv_asset_context is not None:
        http_execution_path.append(
            f"GET /api/scenarios/{scenario_id}/editor-bootstrap"
        )
    http_execution_path.extend(
        [
        f"POST /api/scenarios/{scenario_id}/simulation/prepare",
        f"POST /api/scenarios/{scenario_id}/run-optimization",
        f"GET /api/jobs/{job_id}",
        ]
    )
    if result_response is not None:
        http_execution_path.append(
            f"GET /api/scenarios/{scenario_id}/optimization"
        )
    execution = {
        "schema_version": "frontend_http_case_execution_v1",
        "case": name,
        "scenario_id": scenario_id,
        "prepared_input_id": prepared_input_id,
        "job_id": job_id,
        "job_status": terminal.get("status"),
        "job_error": terminal.get("error"),
        "run_dir": str(run_dir.resolve()) if run_dir else None,
        "started_at_utc": started_utc,
        "completed_at_utc": _utc_now(),
        "total_wall_time_sec": wall_time_sec,
        "frozen_git_sha": frozen_sha,
        "http_execution_path": http_execution_path,
        "optimization_result_received": result_response is not None,
    }
    _write_json(case_dir / "case_execution_metadata.json", execution)
    return {
        **execution,
        "case_dir": str(case_dir.resolve()),
        "prepare_response": prepare_response,
        "terminal_response": terminal,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _uniform_tariff_evidence(
    *,
    case_dir: Path,
    tariff_condition: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify a requested uniform tariff against canonical price-slot output."""

    override_requested = bool(tariff_condition.get("override_requested"))
    if not override_requested:
        return {
            "override_requested": False,
            "accepted": True,
            "reason": "no_uniform_tariff_override_requested",
        }

    expected_price = _number(
        tariff_condition.get("grid_energy_price_yen_per_kwh")
    )
    expected_demand_charge = _number(
        tariff_condition.get("demand_charge_yen_per_kw")
    )
    if expected_price is None or expected_demand_charge is None:
        return {
            "override_requested": True,
            "accepted": False,
            "reason": "invalid_uniform_tariff_condition",
        }

    source_path = case_dir / "simulation_conditions_tou_prices.csv"
    if not source_path.is_file():
        return {
            "override_requested": True,
            "accepted": False,
            "reason": "canonical_tou_price_artifact_missing",
            "source_artifact": source_path.name,
        }
    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error) as exc:
        return {
            "override_requested": True,
            "accepted": False,
            "reason": f"canonical_tou_price_artifact_unreadable:{exc}",
            "source_artifact": source_path.name,
        }

    time_indices: set[int] = set()
    grid_prices: list[float | None] = []
    demand_charge_weights: list[float | None] = []
    malformed_time_index = False
    for row in rows:
        try:
            time_indices.add(int(str(row.get("time_idx") or "")))
        except ValueError:
            malformed_time_index = True
        grid_prices.append(
            _number(row.get("grid_energy_price_yen_per_kwh"))
        )
        demand_charge_weights.append(
            _number(row.get("demand_charge_weight"))
        )
    numeric_values_present = all(
        value is not None
        for value in (*grid_prices, *demand_charge_weights)
    )
    actual_grid_prices = [
        value for value in grid_prices if value is not None
    ]
    actual_demand_charge_weights = [
        value for value in demand_charge_weights if value is not None
    ]
    accepted = (
        len(rows) == 24
        and not malformed_time_index
        and time_indices == set(range(24))
        and numeric_values_present
        and all(
            abs(value - expected_price) <= 1.0e-9
            for value in actual_grid_prices
        )
        and all(
            abs(value - expected_demand_charge) <= 1.0e-9
            for value in actual_demand_charge_weights
        )
    )
    return {
        "override_requested": True,
        "accepted": accepted,
        "source_artifact": source_path.name,
        "expected_grid_energy_price_yen_per_kwh": expected_price,
        "expected_demand_charge_yen_per_kw": expected_demand_charge,
        "observed_row_count": len(rows),
        "observed_time_indices": sorted(time_indices),
        "observed_grid_energy_prices_yen_per_kwh": sorted(
            set(actual_grid_prices)
        ),
        "observed_demand_charge_weights_yen_per_kw": sorted(
            set(actual_demand_charge_weights)
        ),
    }


def _integer_preserving_zero(value: Any, *, default: int) -> int:
    """Convert a present value without treating valid zero as absent."""

    return int(value) if value is not None else int(default)


def _is_present_zero_metric(
    metrics: Mapping[str, Any],
    metric_name: str,
) -> bool:
    """Require an explicit numeric zero; a missing counter never passes."""

    return (
        metric_name in metrics
        and _number(metrics.get(metric_name)) == 0.0
    )


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _write_csv(
    path: Path,
    fieldnames: Iterable[str],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(fieldnames)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _markdown_table(
    headers: list[str],
    rows: Iterable[Iterable[Any]],
) -> list[str]:
    rendered = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    rendered.extend(
        "| " + " | ".join(_format_cell(value) for value in row) + " |"
        for row in rows
    )
    return rendered


def _service_assignments(case_dir: Path) -> dict[str, dict[str, str]]:
    path = case_dir / "vehicle_timelines.csv"
    assignments: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("is_service") or "").strip().lower() != "true":
                continue
            trip_id = str(row.get("trip_id") or "").strip()
            if not trip_id:
                continue
            candidate = {
                "trip_id": trip_id,
                "route": str(row.get("route_id") or ""),
                "departure_time": str(row.get("start_time") or ""),
                "vehicle_id": str(row.get("vehicle_id") or ""),
                "powertrain": str(row.get("vehicle_type") or "").upper(),
            }
            previous = assignments.get(trip_id)
            if previous is not None and previous != candidate:
                raise ValueError(
                    f"Trip {trip_id} has multiple service assignments in {path}"
                )
            assignments[trip_id] = candidate
    return assignments


def _assignment_mix(
    assignments: Mapping[str, Mapping[str, str]],
) -> dict[str, int]:
    used_by_type: dict[str, set[str]] = {"BEV": set(), "ICE": set()}
    trips = {"BEV": 0, "ICE": 0}
    for row in assignments.values():
        category = (
            "BEV"
            if str(row.get("powertrain") or "").upper()
            in POWERTRAIN_ELECTRIC
            else "ICE"
        )
        used_by_type[category].add(str(row.get("vehicle_id") or ""))
        trips[category] += 1
    return {
        "used_bev": len(used_by_type["BEV"] - {""}),
        "used_ice": len(used_by_type["ICE"] - {""}),
        "bev_trips": trips["BEV"],
        "ice_trips": trips["ICE"],
    }


def _vehicle_trip_assignments(
    assignments: Mapping[str, Mapping[str, str]],
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in assignments.values():
        vehicle_id = str(row.get("vehicle_id") or "").strip()
        if not vehicle_id:
            continue
        grouped.setdefault(vehicle_id, []).append(
            {
                "trip_id": str(row.get("trip_id") or ""),
                "route": str(row.get("route") or ""),
                "departure_time": str(row.get("departure_time") or ""),
                "powertrain": str(row.get("powertrain") or ""),
            }
        )
    return {
        vehicle_id: sorted(
            trips,
            key=lambda item: (
                item["departure_time"],
                item["trip_id"],
            ),
        )
        for vehicle_id, trips in sorted(grouped.items())
    }


def _build_assignment_difference(
    *,
    output_dir: Path,
    sunny_dir: Path,
    rain_dir: Path,
) -> dict[str, Any]:
    sunny = _service_assignments(sunny_dir)
    rain = _service_assignments(rain_dir)
    rows: list[dict[str, Any]] = []
    for trip_id in sorted(set(sunny) | set(rain)):
        sunny_row = sunny.get(trip_id, {})
        rain_row = rain.get(trip_id, {})
        sunny_vehicle = str(sunny_row.get("vehicle_id") or "")
        rain_vehicle = str(rain_row.get("vehicle_id") or "")
        sunny_type = str(sunny_row.get("powertrain") or "")
        rain_type = str(rain_row.get("powertrain") or "")
        changed = sunny_vehicle != rain_vehicle
        if not sunny_row or not rain_row:
            change_type = "missing_case_assignment"
        elif not changed:
            change_type = "unchanged"
        elif sunny_type != rain_type:
            change_type = "powertrain_changed"
        else:
            change_type = "vehicle_changed_same_powertrain"
        rows.append(
            {
                "trip_id": trip_id,
                "route": sunny_row.get("route") or rain_row.get("route"),
                "departure_time": (
                    sunny_row.get("departure_time")
                    or rain_row.get("departure_time")
                ),
                "sunny_vehicle_id": sunny_vehicle,
                "sunny_powertrain": sunny_type,
                "rain_vehicle_id": rain_vehicle,
                "rain_powertrain": rain_type,
                "assignment_changed": changed,
                "change_type": change_type,
                # The solver does not expose an additive, solver-native
                # trip-level Stage 2 cost.  Blank is more honest than a
                # proportional allocation presented as provenance.
                "sunny_stage2_cost_contribution": None,
                "rain_stage2_cost_contribution": None,
            }
        )
    fields = [
        "trip_id",
        "route",
        "departure_time",
        "sunny_vehicle_id",
        "sunny_powertrain",
        "rain_vehicle_id",
        "rain_powertrain",
        "assignment_changed",
        "change_type",
        "sunny_stage2_cost_contribution",
        "rain_stage2_cost_contribution",
    ]
    _write_csv(output_dir / "assignment_difference.csv", fields, rows)
    sunny_manifest = _read_json(
        sunny_dir / "comparison_case_manifest.json"
    )
    rain_manifest = _read_json(rain_dir / "comparison_case_manifest.json")
    payload = {
        "schema_version": "frontend_assignment_difference_v1",
        "sunny_assignment_hash": sunny_manifest.get("assignment_hash"),
        "rain_assignment_hash": rain_manifest.get("assignment_hash"),
        "assignment_hashes_equal": (
            sunny_manifest.get("assignment_hash")
            == rain_manifest.get("assignment_hash")
        ),
        "sunny_assignment_mix": _assignment_mix(sunny),
        "rain_assignment_mix": _assignment_mix(rain),
        "sunny_vehicle_trip_assignments": _vehicle_trip_assignments(sunny),
        "rain_vehicle_trip_assignments": _vehicle_trip_assignments(rain),
        "trip_count_union": len(rows),
        "changed_trip_count": sum(
            bool(row["assignment_changed"]) for row in rows
        ),
        "cost_contribution_semantics": (
            "not_available_as_solver_native_additive_trip_cost"
        ),
        "source_artifacts": {
            "sunny": "sunny/vehicle_timelines.csv",
            "rain": "rain/vehicle_timelines.csv",
        },
        "rows": rows,
    }
    _write_json(output_dir / "assignment_difference.json", payload)
    md = [
        "# Assignment difference",
        "",
        f"- Sunny assignment hash: `{payload['sunny_assignment_hash']}`",
        f"- Rain assignment hash: `{payload['rain_assignment_hash']}`",
        (
            "- Assignment hashes equal: "
            f"`{str(payload['assignment_hashes_equal']).lower()}`"
        ),
        f"- Changed trips: `{payload['changed_trip_count']}`",
        "",
        (
            "> Per-trip Stage 2 cost contribution is blank because no "
            "solver-native additive trip-cost provenance exists."
        ),
        "",
        *_markdown_table(
            [
                "Trip",
                "Departure",
                "Sunny vehicle",
                "Sunny type",
                "Rain vehicle",
                "Rain type",
                "Change",
            ],
            (
                (
                    row["trip_id"],
                    row["departure_time"],
                    row["sunny_vehicle_id"],
                    row["sunny_powertrain"],
                    row["rain_vehicle_id"],
                    row["rain_powertrain"],
                    row["change_type"],
                )
                for row in rows
                if row["assignment_changed"]
            ),
        ),
        "",
        "## Sunny vehicle duties",
        "",
        *_markdown_table(
            ["Vehicle", "Powertrain", "Trips"],
            (
                (
                    vehicle_id,
                    trips[0]["powertrain"] if trips else "",
                    ", ".join(trip["trip_id"] for trip in trips),
                )
                for vehicle_id, trips in payload[
                    "sunny_vehicle_trip_assignments"
                ].items()
            ),
        ),
        "",
        "## Rain vehicle duties",
        "",
        *_markdown_table(
            ["Vehicle", "Powertrain", "Trips"],
            (
                (
                    vehicle_id,
                    trips[0]["powertrain"] if trips else "",
                    ", ".join(trip["trip_id"] for trip in trips),
                )
                for vehicle_id, trips in payload[
                    "rain_vehicle_trip_assignments"
                ].items()
            ),
        ),
        "",
    ]
    (output_dir / "assignment_difference.md").write_text(
        "\n".join(md),
        encoding="utf-8",
    )
    return payload


def _solver_row(case: str, case_dir: Path) -> dict[str, Any]:
    settings = _read_json(case_dir / "solver_settings.json")
    summary = _read_json(case_dir / "summary.json")
    input_audit = _read_json(case_dir / "input_audit.json")
    comparison = _read_json(case_dir / "comparison_case_manifest.json")
    chain = _read_json(
        case_dir
        / "rolling_hourly_chain"
        / "rolling_chain_summary.json"
    )
    execution = _read_json(case_dir / "case_execution_metadata.json")
    telemetry = dict(settings.get("stage1_search_telemetry") or {})
    telemetry_final = dict(telemetry.get("final") or {})
    steps = list(chain.get("steps") or ())
    rolling_solver_total = sum(
        float(dict(step).get("stage2_runtime_seconds") or 0.0)
        for step in steps
        if isinstance(step, Mapping)
    )
    return {
        "case": case,
        "run_id": Path(
            str(execution.get("run_dir") or case_dir.name)
        ).name,
        "git_sha": settings.get("git_sha"),
        "prepared_input_id": input_audit.get("prepared_input_id"),
        "total_wall_time_sec": execution.get("total_wall_time_sec"),
        "day_ahead_total_sec": summary.get("solve_time_seconds"),
        "stage1_runtime_sec": settings.get("stage1_runtime_seconds"),
        "stage2_runtime_sec": settings.get("stage2_runtime_seconds"),
        "first_incumbent_sec": telemetry.get(
            "first_incumbent_runtime_sec"
        ),
        "rolling_solver_total_sec": rolling_solver_total,
        "stage1_raw_best_bound": settings.get(
            "stage1_gurobi_raw_best_bound"
        ),
        "stage1_raw_gap": settings.get(
            "stage1_gurobi_raw_mip_gap_ratio"
        ),
        "stage1_certified_best_bound": settings.get(
            "stage1_certified_best_bound"
        ),
        "stage1_certified_gap": settings.get(
            "stage1_certified_mip_gap_ratio"
        ),
        "requested_gap": settings.get("mip_gap_requested_ratio"),
        "termination_reason": settings.get("stage1_termination_reason"),
        "node_count": telemetry_final.get("explored_node_count"),
        "feedback_iteration_count": settings.get(
            "stage2_feedback_iteration"
        ),
        "candidate_count": settings.get(
            "stage1_stage2_candidate_count_evaluated"
        ),
        **_assignment_mix(_service_assignments(case_dir)),
        "assignment_hash": comparison.get("assignment_hash"),
    }


def _build_solver_comparison(
    output_dir: Path,
    sunny_dir: Path,
    rain_dir: Path,
) -> list[dict[str, Any]]:
    rows = [
        _solver_row("sunny", sunny_dir),
        _solver_row("rain", rain_dir),
    ]
    fields = list(rows[0])
    _write_csv(output_dir / "solver_comparison.csv", fields, rows)
    md = [
        "# Solver comparison",
        "",
        (
            "> Each case was executed once. These wall times are provenance "
            "measurements, not evidence of a weather-caused runtime effect."
        ),
        "",
        *_markdown_table(
            ["Metric", "Sunny", "Rain"],
            (
                (field, rows[0].get(field), rows[1].get(field))
                for field in fields
                if field != "case"
            ),
        ),
        "",
    ]
    (output_dir / "solver_comparison.md").write_text(
        "\n".join(md),
        encoding="utf-8",
    )
    return rows


def _bess_initial_soc(case_dir: Path) -> float | None:
    conditions = _read_json(case_dir / "simulation_conditions.json")
    assets = conditions.get("depot_energy_assets")
    if isinstance(assets, Mapping):
        assets = [assets]
    values = [
        _number(dict(asset).get("bess_initial_soc_kwh"))
        for asset in list(assets or ())
        if isinstance(asset, Mapping)
    ]
    finite = [value for value in values if value is not None]
    return sum(finite) if finite else None


def _bess_terminal_soc(case_dir: Path) -> float | None:
    executed = _read_json(
        case_dir
        / "rolling_hourly_chain"
        / "executed_day_accounting.json"
    )
    raw = dict(executed.get("bess_terminal_soc_by_depot") or {})
    values = [
        _number(
            dict(value).get("terminal_soc_kwh")
            if isinstance(value, Mapping)
            else value
        )
        for value in raw.values()
    ]
    finite = [value for value in values if value is not None]
    return sum(finite) if finite else None


def _research_values(
    case_dir: Path,
    solver_row: Mapping[str, Any],
) -> dict[str, tuple[Any, str, str]]:
    kpi = _read_json(case_dir / "kpi_summary.json")
    executed = _read_json(
        case_dir
        / "rolling_hourly_chain"
        / "executed_day_accounting.json"
    )
    cost = dict(executed.get("cost_breakdown") or {})
    return {
        "PV generation": (
            cost.get("pv_generated_kwh"),
            "kWh",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "Grid import": (
            cost.get("grid_import_kwh"),
            "kWh",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "PV to bus": (
            cost.get("pv_to_bus_kwh"),
            "kWh",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "PV to BESS": (
            cost.get("pv_to_bess_kwh"),
            "kWh",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "BESS to bus": (
            cost.get("bess_to_bus_kwh"),
            "kWh",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "PV curtailed": (
            cost.get("pv_curtailed_kwh"),
            "kWh",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "Peak grid import": (
            cost.get("peak_grid_kw"),
            "kW",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "Bus charging": (
            sum(
                float(cost.get(key) or 0.0)
                for key in (
                    "grid_to_bus_kwh",
                    "pv_to_bus_kwh",
                    "bess_to_bus_kwh",
                )
            ),
            "kWh",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "BESS start SOC": (
            _bess_initial_soc(case_dir),
            "kWh",
            "simulation_conditions.json",
        ),
        "BESS end SOC": (
            _bess_terminal_soc(case_dir),
            "kWh",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "Used BEV": (
            solver_row.get("used_bev"),
            "vehicles",
            "vehicle_timelines.csv",
        ),
        "Used ICE": (
            solver_row.get("used_ice"),
            "vehicles",
            "vehicle_timelines.csv",
        ),
        "BEV trips": (
            solver_row.get("bev_trips"),
            "trips",
            "vehicle_timelines.csv",
        ),
        "ICE trips": (
            solver_row.get("ice_trips"),
            "trips",
            "vehicle_timelines.csv",
        ),
        "Fuel consumption": (
            kpi.get("ice_fuel_consumed_l"),
            "L",
            "kpi_summary.json",
        ),
        "Electricity cost": (
            cost.get("electricity_cost"),
            "JPY",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "Fuel cost": (
            cost.get("fuel_cost"),
            "JPY",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "Demand charge": (
            cost.get("demand_cost"),
            "JPY",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "Total cost": (
            cost.get("total_cost"),
            "JPY",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "CO2": (
            cost.get("total_co2_kg"),
            "kgCO2",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        "Total wall time": (
            solver_row.get("total_wall_time_sec"),
            "s",
            "case_execution_metadata.json",
        ),
        "Certified MILP gap": (
            solver_row.get("stage1_certified_gap"),
            "ratio",
            "solver_settings.json",
        ),
    }


def _difference(sunny: Any, rain: Any) -> float | None:
    left = _number(sunny)
    right = _number(rain)
    return None if left is None or right is None else right - left


def _build_research_comparison(
    output_dir: Path,
    sunny_dir: Path,
    rain_dir: Path,
    solver_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sunny_values = _research_values(sunny_dir, solver_rows[0])
    rain_values = _research_values(rain_dir, solver_rows[1])
    rows: list[dict[str, Any]] = []
    for metric in sunny_values:
        sunny_value, unit, sunny_source = sunny_values[metric]
        rain_value, rain_unit, rain_source = rain_values[metric]
        if unit != rain_unit:
            raise ValueError(f"Unit mismatch for research metric {metric}")
        rows.append(
            {
                "metric": metric,
                "unit": unit,
                "sunny": sunny_value,
                "rain": rain_value,
                "rain_minus_sunny": _difference(
                    sunny_value,
                    rain_value,
                ),
                "sunny_source_artifact": f"sunny/{sunny_source}",
                "rain_source_artifact": f"rain/{rain_source}",
            }
        )
    fields = list(rows[0])
    _write_csv(output_dir / "research_comparison.csv", fields, rows)
    md = [
        "# Controlled same-service-date PV supply sensitivity",
        "",
        (
            "This is a high-PV/low-PV supply sensitivity under the same "
            "2025-08-05 weekday service. It is not an observed sunny-day "
            "versus rainy-day operations comparison."
        ),
        "",
        *_markdown_table(
            [
                "Metric",
                "Sunny",
                "Rain",
                "Rain - Sunny",
                "Unit",
                "Sources",
            ],
            (
                (
                    row["metric"],
                    row["sunny"],
                    row["rain"],
                    row["rain_minus_sunny"],
                    row["unit"],
                    (
                        f"{row['sunny_source_artifact']}; "
                        f"{row['rain_source_artifact']}"
                    ),
                )
                for row in rows
            ),
        ),
        "",
    ]
    (output_dir / "research_comparison.md").write_text(
        "\n".join(md),
        encoding="utf-8",
    )
    return rows


def _claim_artifacts_consistent(
    *,
    settings: Mapping[str, Any],
    optimization_result: Mapping[str, Any],
    terminal_response: Mapping[str, Any],
) -> bool:
    """Fail closed when terminal prose contradicts persisted claim gates."""

    classification = dict(
        optimization_result.get("result_claim_classification") or {}
    )
    if (
        classification.get("label") != "feasible_candidate"
        or terminal_response.get("status") != "completed"
    ):
        return False

    settings_gap_met = settings.get("mip_gap_target_met") is True
    if classification.get("mip_gap_target_met") is not settings_gap_met:
        return False

    blockers = set(classification.get("optimality_blocking_reasons") or [])
    message = str(terminal_response.get("message") or "")
    interpretation = str(classification.get("interpretation") or "")
    mentions_gap_failure = (
        "requested MIP gap" in message and "not established" in message
    )
    certified_gap = _number(classification.get("certified_mip_gap"))

    if settings_gap_met:
        gap_phrase = (
            "certified Stage 1 MIP gap target passed"
            if certified_gap is not None
            else "requested MIP gap target passed"
        )
        gap_semantics_match = (
            gap_phrase in message
            and not mentions_gap_failure
            and "meeting the" in interpretation
            and "MIP gap target" in interpretation
        )
    else:
        gap_semantics_match = (
            mentions_gap_failure
            and "meeting the certified Stage 1 MIP gap target"
            not in interpretation
            and "meeting the requested MIP gap target"
            not in interpretation
        )

    integrated_scope_match = (
        "not_an_integrated_global_assignment_and_charging_milp"
        not in blockers
        or (
            "integrated global optimality" in message
            and "not established" in message
        )
    )
    return gap_semantics_match and integrated_scope_match


def _phase4_warm_start_evidence_valid(
    *,
    seed_audit: Mapping[str, Any],
    integrated_start_audit: Mapping[str, Any],
) -> bool:
    """Require a same-problem, physical Stage 2 seed and full discrete start."""

    seed_fingerprint = str(
        seed_audit.get("seed_plan_fingerprint") or ""
    )
    start_fingerprint = str(
        integrated_start_audit.get("seed_plan_fingerprint") or ""
    )
    valid_fingerprint = bool(
        len(seed_fingerprint) == 64
        and all(
            character in "0123456789abcdef"
            for character in seed_fingerprint
        )
    )
    integrated_solution_fingerprint = str(
        integrated_start_audit.get("integrated_solution_start_fingerprint")
        or ""
    )
    valid_integrated_solution_fingerprint = bool(
        len(integrated_solution_fingerprint) == 64
        and all(
            character in "0123456789abcdef"
            for character in integrated_solution_fingerprint
        )
    )
    return bool(
        seed_audit.get("accepted") is True
        and seed_audit.get("same_canonical_problem") is True
        and seed_audit.get("seed_exact_trip_set_match") is True
        and seed_audit.get("seed_stage2_feasible") is True
        and seed_audit.get("seed_independent_physical_feasible") is True
        and valid_fingerprint
        and integrated_start_audit.get("applied") is True
        and integrated_start_audit.get("same_canonical_problem") is True
        and integrated_start_audit.get(
            "complete_assignment_binary_start"
        )
        is True
        and integrated_start_audit.get(
            "complete_charger_binary_start"
        )
        is True
        and integrated_start_audit.get(
            "complete_bess_mode_binary_start"
        )
        is True
        and integrated_start_audit.get("complete_vehicle_soc_start")
        is True
        and integrated_start_audit.get("complete_bess_soc_start") is True
        and integrated_start_audit.get("physical_energy_trace_start")
        is True
        and integrated_start_audit.get(
            "dispatch_fixed_recourse_requested"
        )
        is True
        and integrated_start_audit.get(
            "integrated_dispatch_fixed_recourse_feasible"
        )
        is True
        and integrated_start_audit.get(
            "integrated_feasible_start_applied"
        )
        is True
        and integrated_start_audit.get(
            "complete_integrated_solution_start"
        )
        is True
        and (_number(
            integrated_start_audit.get("integrated_solution_start_count")
        ) or 0.0)
        > 0.0
        and valid_integrated_solution_fingerprint
        and start_fingerprint == seed_fingerprint
    )


def _case_gate_audit(
    *,
    name: str,
    case_dir: Path,
    prepared_trip_count: int,
    frozen_sha: str,
    tariff_condition: Mapping[str, Any],
    optimization_experiment_case: str = "phase3_baseline",
) -> dict[str, Any]:
    summary = _read_json(case_dir / "summary.json")
    settings = _read_json(case_dir / "solver_settings.json")
    physical = _read_json(
        case_dir / "physical_schedule_validation.json"
    )
    physical_metrics = dict(physical.get("validation_metrics") or {})
    solver_metrics = dict(physical.get("solver_validation_metrics") or {})
    chain = _read_json(
        case_dir
        / "rolling_hourly_chain"
        / "rolling_chain_summary.json"
    )
    executed = _read_json(
        case_dir
        / "rolling_hourly_chain"
        / "executed_day_accounting.json"
    )
    reconciliation = _read_json(
        case_dir / "final_cost_reconciliation.json"
    )
    completeness = _read_json(case_dir / "artifact_completeness.json")
    assignment_economic_audit = _read_json(
        case_dir / "assignment_economic_audit.json"
    )
    composition_search = _read_json_optional(
        case_dir / "stage1_used_powertrain_composition_search.json"
    )
    acceptance = dict(settings.get("research_acceptance_checks") or {})
    search_telemetry = dict(
        settings.get("stage1_search_telemetry") or {}
    )
    final_search_telemetry = dict(
        search_telemetry.get("final") or {}
    )
    input_audit = _read_json(case_dir / "input_audit.json")
    tariff_evidence = _uniform_tariff_evidence(
        case_dir=case_dir,
        tariff_condition=tariff_condition,
    )
    prepare_response = _read_json(
        case_dir / "frontend_prepare_response.json"
    )
    optimization_result_response = _read_json(
        case_dir / "frontend_optimization_result_response.json"
    )
    terminal_response = _read_json(
        case_dir / "frontend_job_terminal_response.json"
    )
    audited_prepared_input_id = str(
        input_audit.get("prepared_input_id") or ""
    ).strip()
    response_prepared_input_id = str(
        prepare_response.get("preparedInputId") or ""
    ).strip()
    phase4_actual_cost = (
        optimization_experiment_case
        == "phase4_integrated_actual_cost"
    )
    phase4_policy = optimization_experiment_case in {
        "phase4_maximum_ev_utilization",
        "phase4_cost_constrained_ev_utilization",
    }
    phase4_integrated = phase4_actual_cost or phase4_policy
    requested_gap_ratio = 0.05 if phase4_integrated else 0.1
    phase4_policy_cost_cap_valid = bool(
        not phase4_policy
        or (
            optimization_experiment_case
            == "phase4_maximum_ev_utilization"
            and settings.get("integrated_actual_cost_upper_bound_jpy") is None
        )
        or (
            optimization_experiment_case
            == "phase4_cost_constrained_ev_utilization"
            and _number(
                settings.get("integrated_actual_cost_upper_bound_jpy")
            )
            is not None
            and settings.get(
                "integrated_actual_cost_upper_bound_verified"
            )
            is True
        )
    )
    phase3_frontier = (
        optimization_experiment_case == "phase3_bev_frontier"
    )
    frontier_target_records = list(
        composition_search.get("target_records") or []
    )
    expected_frontier_target_count = 35 - 15 + 1
    phase4_phase3_seed_audit = dict(
        settings.get("phase4_phase3_seed_audit") or {}
    )
    integrated_warm_start_audit = dict(
        settings.get("integrated_warm_start_audit") or {}
    )
    phase4_telemetry_complete = bool(
        _number(settings.get("solve_time_sec")) is not None
        and bool(str(settings.get("solver_termination_reason") or "").strip())
        and settings.get("has_feasible_incumbent") is True
        and int(settings.get("incumbent_count") or 0) >= 1
        and _number(settings.get("first_feasible_sec")) is not None
        and _number(settings.get("nodes_explored")) is not None
    )
    phase3_telemetry_complete = bool(
        all(
            _number(value) is not None
            for value in (
                settings.get("stage1_runtime_seconds"),
                settings.get("stage2_runtime_seconds"),
                settings.get("stage1_gurobi_raw_best_bound"),
                settings.get("stage1_gurobi_raw_mip_gap_ratio"),
                settings.get("stage1_certified_best_bound"),
                settings.get("stage1_certified_mip_gap_ratio"),
                search_telemetry.get("first_incumbent_runtime_sec"),
                final_search_telemetry.get("explored_node_count"),
            )
        )
        and bool(
            str(settings.get("stage1_termination_reason") or "").strip()
        )
    )
    frontier_selection_complete = bool(
        composition_search.get("frontier_enabled") is True
        and composition_search.get("frontier_total_used_vehicle_count_fixed")
        is False
        and len(frontier_target_records) == expected_frontier_target_count
        and composition_search.get("all_requested_targets_resolved") is True
        and not list(composition_search.get("unresolved_targets") or [])
        and int(
            settings.get("stage1_stage2_feasible_candidate_count") or 0
        )
        >= 1
        and bool(
            str(
                settings.get("stage1_stage2_selected_candidate_hash") or ""
            ).strip()
        )
        and _number(
            settings.get(
                "stage1_stage2_selected_canonical_actual_cost_jpy"
            )
        )
        is not None
    )
    phase3_baseline_selection_complete = bool(
        int(settings.get("stage1_distinct_candidate_count") or 0) >= 10
        and int(
            settings.get("stage1_stage2_candidate_count_evaluated") or 0
        )
        >= 10
        and int(
            settings.get("stage1_stage2_feasible_candidate_count") or 0
        )
        >= 1
        and int(
            settings.get("stage1_stage2_selected_candidate_index") or 0
        )
        >= 1
        and bool(
            str(
                settings.get("stage1_stage2_selected_candidate_hash") or ""
            ).strip()
        )
        and _number(
            settings.get(
                "stage1_stage2_selected_canonical_actual_cost_jpy"
            )
        )
        is not None
    )
    certified_gap = _number(
        settings.get(
            "achieved_mip_gap"
            if phase4_integrated
            else "stage1_certified_mip_gap_ratio"
        )
    )
    zero_metric_names = (
        "unassigned_trip_count",
        "duplicate_trip_count",
        "unknown_vehicle_count",
        "vehicle_time_overlap_count",
        "infeasible_transition_count",
        "location_discontinuity_count",
        "unknown_operator_count",
        "blank_charger_id_count",
        "unknown_charger_id_count",
        "charger_depot_mismatch_count",
        "charging_location_violation_count",
        "charger_compatibility_violation_count",
        "charger_power_violation_count",
        "charger_concurrency_violation_count",
        "ev_soc_lower_violation_count",
        "ev_soc_upper_violation_count",
        "bev_terminal_soc_violation_count",
        "refueling_location_violation_count",
        "refueling_powertrain_violation_count",
        "fuel_lower_violation_count",
        "fuel_upper_violation_count",
    )

    checks: dict[str, bool] = {
        "fresh_prepared_input": (
            bool(audited_prepared_input_id)
            and audited_prepared_input_id == response_prepared_input_id
            and audited_prepared_input_id
            not in FORBIDDEN_PREPARED_INPUT_IDS
        ),
        "git_sha_matches_frozen": (
            settings.get("git_sha") == frozen_sha
            and settings.get("git_sha_after_solve") == frozen_sha
            and settings.get("git_state_unchanged_during_solve") is True
            and chain.get("day_ahead_git_sha") == frozen_sha
            and chain.get("rolling_runner_git_sha") == frozen_sha
        ),
        "git_clean": (
            settings.get("git_state_available") is True
            and settings.get("git_dirty") is False
            and settings.get("git_dirty_after_solve") is False
            and chain.get("rolling_runner_git_dirty") is False
        ),
        "prepared_scope_all_trips_served": (
            int(prepared_trip_count) > 0
            and _integer_preserving_zero(
                summary.get("trip_count_served"),
                default=-1,
            )
            == int(prepared_trip_count)
            and _integer_preserving_zero(
                summary.get("trip_count_unserved"),
                default=-1,
            )
            == 0
        ),
        "physical_schedule_accepted": physical.get("accepted") is True,
        "physical_all_required_checks_passed": bool(
            _nested(
                physical,
                "checks",
                "all_required_hard_validation_checks_passed",
            )
        ),
        "physical_zero_metrics": all(
            _is_present_zero_metric(physical_metrics, metric)
            for metric in zero_metric_names
        ),
        "grid_contract_zero": _is_present_zero_metric(
            solver_metrics,
            "contract_power_violation_count",
        ),
        "bess_soc_zero": all(
            _is_present_zero_metric(solver_metrics, metric)
            for metric in (
                "bess_soc_lower_violation_count",
                "bess_soc_upper_violation_count",
                "bess_soc_violation_count",
            )
        ),
        "bev_terminal_accepted": bool(
            _nested(physical, "checks", "bev_terminal_energy_balanced")
        ),
        "bess_terminal_accepted": bool(
            _nested(physical, "checks", "bess_terminal_energy_balanced")
        ),
        "no_fallback": (
            settings.get("fallback_applied") is False
            and acceptance.get("no_fallback") is True
        ),
        "no_postsolve_repair": (
            acceptance.get("no_postsolve_modification") is True
        ),
        "rolling_24_of_24": (
            int(chain.get("expected_step_count") or -1) == 24
            and int(chain.get("step_count") or -1) == 24
            and chain.get("chain_accepted") is True
        ),
        "rolling_assignment_constant": bool(
            _nested(
                chain,
                "acceptance_checks",
                "day_ahead_assignment_hash_constant",
            )
        ),
        "executed_day_accounting_eligible": (
            executed.get("eligible") is True
        ),
        "final_cost_reconciliation_ok": (
            reconciliation.get("status") == "OK"
        ),
        "artifact_completeness_ok": (
            completeness.get("status") == "OK"
            and completeness.get("accepted") is True
        ),
        "certified_gap_at_most_requested": (
            certified_gap is not None
            and certified_gap <= requested_gap_ratio + 1.0e-12
        ),
        "solver_controls_match_formal_request": (
            settings.get("time_limit_seconds_requested")
            == (3600 if (phase4_integrated or phase3_frontier) else 1800)
            and (
                phase4_integrated
                or settings.get("stage1_time_limit_seconds_requested")
                == (3000 if phase3_frontier else 1500)
            )
            and (
                phase4_integrated
                or settings.get("stage2_time_limit_seconds_requested")
                == (600 if phase3_frontier else 300)
            )
            and _number(settings.get("mip_gap_requested_ratio"))
            == requested_gap_ratio
            and settings.get("stage1_best_obj_stop_enabled") is False
            and settings.get("gurobi_threads") == 1
            and settings.get("random_seed") == 42
            and int(
                settings.get(
                    "stage1_stage2_candidate_limit_requested"
                )
                or 0
            )
            >= (1 if phase4_integrated else 22 if phase3_frontier else 10)
            and int(
                settings.get("stage1_composition_search_radius_requested")
                or 0
            ) >= (0 if (phase4_integrated or phase3_frontier) else 2)
            and (
                not phase3_frontier
                or settings.get("stage1_bev_frontier_enabled") is True
            )
            and (
                not phase4_actual_cost
                or settings.get("integrated_actual_cost_objective_requested")
                is True
            )
            and (
                not phase4_integrated
                or settings.get("phase4_phase3_seed_enabled") is True
                and settings.get("phase4_phase3_seed_time_limit_sec") == 600
                and settings.get(
                    "phase4_phase3_seed_stage1_time_limit_sec"
                )
                == 480
                and settings.get(
                    "phase4_phase3_seed_stage2_time_limit_sec"
                )
                == 120
                and settings.get("phase4_phase3_seed_candidate_limit") == 10
                and settings.get(
                    "phase4_phase3_seed_composition_search_radius"
                )
                == 2
                and settings.get(
                    "phase4_phase3_seed_search_directionality"
                )
                == "primary_plus_symmetric_adjacent_compositions"
                and settings.get(
                    "phase4_phase3_seed_bev_frontier_enabled"
                )
                is False
                and settings.get(
                    "phase4_integrated_seed_recourse_preflight_enabled"
                )
                is True
                and settings.get(
                    "phase4_integrated_seed_recourse_time_limit_sec"
                )
                == 300
                and settings.get(
                    "phase4_integrated_seed_recourse_preflight_requested"
                )
                is True
                and settings.get(
                    "phase4_integrated_seed_recourse_preflight_feasible"
                )
                is True
                and settings.get("phase4_total_solver_time_budget_sec")
                == 4500
            )
            and (
                not phase4_policy
                or settings.get("integrated_actual_cost_contract_applied")
                is True
                and settings.get("integrated_ev_utilization_mode")
                == "minimum_ice_fuel_lexicographic"
                and phase4_policy_cost_cap_valid
            )
        ),
        "tariff_condition_verified_from_canonical_slots": (
            tariff_evidence.get("accepted") is True
        ),
        "solver_telemetry_complete": (
            phase4_telemetry_complete
            if phase4_integrated
            else phase3_telemetry_complete
        ),
        "phase4_verified_same_problem_warm_start": (
            not phase4_integrated
            or _phase4_warm_start_evidence_valid(
                seed_audit=phase4_phase3_seed_audit,
                integrated_start_audit=integrated_warm_start_audit,
            )
        ),
        "candidate_evidence_present": (
            phase4_integrated
            or (case_dir / "stage1_stage2_candidate_evaluation.json").is_file()
            and (
                case_dir / "stage1_stage2_candidate_evaluation.csv"
            ).is_file()
        ),
        "assignment_economic_audit_present": (
            (case_dir / "assignment_economic_audit.json").is_file()
            and (case_dir / "assignment_economic_audit.csv").is_file()
            and assignment_economic_audit.get("schema_version")
            == "assignment_economic_audit_v1"
            and all(
                key in assignment_economic_audit
                for key in (
                    "bev_grid_marginal_cost_jpy_per_km",
                    "ice_marginal_cost_jpy_per_km",
                    "renewable_budget_kwh",
                    "renewable_energy_allocated_in_stage1_kwh",
                    "grid_energy_allocated_in_stage1_kwh",
                    "stage1_bev_trip_count",
                    "stage2_bev_trip_count",
                    "assignment_energy_coupling_mode",
                    "weather_response_expected",
                    "weather_response_observed",
                )
            )
        ),
        "used_powertrain_composition_search_certified": (
            phase4_integrated
            or (
                composition_search.get("schema_version")
                == (
                    "stage1_used_powertrain_composition_search_v2"
                    if phase3_frontier
                    else "stage1_used_powertrain_composition_search_v1"
                )
                and composition_search.get(
                    "accepted_for_formal_composition_evidence"
                )
                is True
                and settings.get(
                    "stage1_used_powertrain_composition_search_accepted"
                )
                is True
            )
        ),
        "solver_objective_matches_canonical_accounting": (
            (
                summary.get("solver_objective_matches_accounting_total")
                is False
                and settings.get(
                    "actual_cost_objective_structural_contract_passed"
                )
                is True
                and settings.get("integrated_actual_cost_contract_applied")
                is True
                and settings.get("integrated_primary_objective_kind")
                == "minimum_ice_fuel_lexicographic"
            )
            if phase4_policy
            else (
                summary.get("solver_objective_matches_accounting_total")
                is True
                and (
                    not phase4_actual_cost
                    or settings.get(
                        "actual_cost_objective_structural_contract_passed"
                    )
                    is True
                    and settings.get(
                        "actual_cost_objective_numeric_reconciliation_passed"
                    )
                    is True
                )
            )
        ),
        "candidate_selection_complete": (
            True
            if phase4_integrated
            else (
                frontier_selection_complete
                if phase3_frontier
                else phase3_baseline_selection_complete
            )
        ),
        "slot_energy_recourse_used": (
            (
                (
                    settings.get(
                        "integrated_actual_cost_objective_requested"
                    )
                    is True
                    if phase4_actual_cost
                    else settings.get(
                        "integrated_actual_cost_contract_applied"
                    )
                    is True
                )
                and settings.get("executed_phase") == "phase4_integrated"
            )
            if phase4_integrated
            else (
                settings.get("stage1_energy_cost_proxy_used_in_objective")
                is False
                and _nested(
                    settings,
                    "stage1_time_indexed_energy_recourse_configuration",
                    "used_in_stage1_objective",
                )
                is True
                and _nested(
                    settings,
                    "stage1_time_indexed_energy_recourse_configuration",
                    "arbitrary_weather_assignment_bias_used",
                )
                is False
            )
        ),
        "terminal_claim_message_consistent": _claim_artifacts_consistent(
            settings=settings,
            optimization_result=optimization_result_response,
            terminal_response=terminal_response,
        ),
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    return {
        "case": name,
        "accepted": not failed,
        "checks": checks,
        "failed_checks": failed,
        "prepared_trip_count": prepared_trip_count,
        "served_trip_count": summary.get("trip_count_served"),
        "certified_gap": certified_gap,
        "tariff_evidence": tariff_evidence,
    }


def _candidate_rows(case_dir: Path, case: str) -> list[dict[str, Any]]:
    payload = _read_json_optional(
        case_dir / "stage1_stage2_candidate_evaluation.json"
    )
    raw = payload.get("candidates")
    if raw is None:
        raw = payload.get("stage1_stage2_candidate_evaluation")
    if raw is None and isinstance(payload.get("evaluations"), list):
        raw = payload.get("evaluations")
    rows: list[dict[str, Any]] = []
    for candidate in list(raw or ()):
        if not isinstance(candidate, Mapping):
            continue
        rows.append({"case": case, **dict(candidate)})
    return rows


def _build_same_assignment_investigation(
    *,
    output_dir: Path,
    sunny_dir: Path,
    rain_dir: Path,
    assignment: Mapping[str, Any],
) -> dict[str, Any]:
    sunny_settings = _read_json(sunny_dir / "solver_settings.json")
    rain_settings = _read_json(rain_dir / "solver_settings.json")
    sunny_manifest = _read_json(
        sunny_dir / "comparison_case_manifest.json"
    )
    rain_manifest = _read_json(rain_dir / "comparison_case_manifest.json")
    candidate_payloads = {
        "sunny": _read_json_optional(
            sunny_dir / "stage1_stage2_candidate_evaluation.json"
        ),
        "rain": _read_json_optional(
            rain_dir / "stage1_stage2_candidate_evaluation.json"
        ),
    }
    candidates_by_case = {
        "sunny": _candidate_rows(sunny_dir, "sunny"),
        "rain": _candidate_rows(rain_dir, "rain"),
    }
    candidates = [
        *candidates_by_case["sunny"],
        *candidates_by_case["rain"],
    ]
    alternative_cost_fields = [
        "case",
        "candidate_index",
        "stage1_pool_solution_index",
        "candidate_hash",
        "assignment_hash",
        "stage1_relaxed_objective_jpy",
        "stage1_recourse_objective_jpy",
        "stage2_exact_objective_jpy",
        "stage2_actual_canonical_cost_jpy",
        "feasible",
        "stage2_solver_status",
        "used_bev",
        "used_ice",
        "bev_trips",
        "ice_trips",
        "runtime_sec",
        "iis_hash",
    ]
    _write_csv(
        output_dir / "same_assignment_alternative_costs.csv",
        alternative_cost_fields,
        candidates,
    )
    selected_hash_by_case = {
        case: str(
            payload.get("selected_candidate_hash") or ""
        )
        for case, payload in candidate_payloads.items()
    }
    alternatives_by_case: dict[str, set[str]] = {
        "sunny": set(),
        "rain": set(),
    }
    feasible_alternatives_by_case: dict[str, set[str]] = {
        "sunny": set(),
        "rain": set(),
    }
    for row in candidates:
        case = str(row.get("case") or "")
        candidate_hash = str(
            row.get("assignment_hash") or row.get("candidate_hash") or ""
        )
        if (
            case not in alternatives_by_case
            or not candidate_hash
            or candidate_hash == selected_hash_by_case.get(case)
        ):
            continue
        alternatives_by_case[case].add(candidate_hash)
        if row.get("feasible") is True:
            feasible_alternatives_by_case[case].add(candidate_hash)

    selected_candidate_by_case: dict[str, dict[str, Any]] = {}
    selected_is_minimum_by_case: dict[str, bool] = {}
    selected_recourse_objective_by_case: dict[str, float | None] = {}
    exchange_rows: list[dict[str, Any]] = []
    duty_overlap_rows: list[dict[str, Any]] = []
    assignment_details_complete_by_case: dict[str, bool] = {}
    selected_overlap_complete_by_case: dict[str, bool] = {}
    exchange_candidate_count_by_case = {"sunny": 0, "rain": 0}
    for case, case_candidates in candidates_by_case.items():
        selected_hash = selected_hash_by_case[case]
        selected = next(
            (
                row
                for row in case_candidates
                if str(
                    row.get("assignment_hash")
                    or row.get("candidate_hash")
                    or ""
                )
                == selected_hash
            ),
            {},
        )
        selected_candidate_by_case[case] = selected
        selected_cost = _number(
            selected.get("stage2_actual_canonical_cost_jpy")
        )
        feasible_costs = [
            value
            for value in (
                _number(
                    row.get("stage2_actual_canonical_cost_jpy")
                )
                for row in case_candidates
                if row.get("feasible") is True
            )
            if value is not None
        ]
        selected_is_minimum_by_case[case] = bool(
            selected_cost is not None
            and feasible_costs
            and selected_cost <= min(feasible_costs) + 1.0e-6
        )
        selected_recourse_objective_by_case[case] = _number(
            selected.get("stage1_recourse_objective_jpy")
        )

        assignment_details_complete_by_case[case] = bool(
            case_candidates
            and all(
                isinstance(
                    row.get("vehicle_trip_assignments"),
                    list,
                )
                and bool(row.get("vehicle_trip_assignments"))
                for row in case_candidates
                if row.get("stage2_solver_status")
                != "not_run_feedback_budget_reserved"
            )
        )
        selected_assignments = {
            str(item.get("trip_id") or ""): dict(item)
            for item in list(
                selected.get("vehicle_trip_assignments") or ()
            )
            if isinstance(item, Mapping)
            and str(item.get("trip_id") or "")
        }
        for row in case_candidates:
            candidate_hash = str(
                row.get("assignment_hash")
                or row.get("candidate_hash")
                or ""
            )
            if not candidate_hash or candidate_hash == selected_hash:
                continue
            candidate_assignments = {
                str(item.get("trip_id") or ""): dict(item)
                for item in list(
                    row.get("vehicle_trip_assignments") or ()
                )
                if isinstance(item, Mapping)
                and str(item.get("trip_id") or "")
            }
            exchanged_trip_ids = sorted(
                trip_id
                for trip_id in set(selected_assignments)
                & set(candidate_assignments)
                if str(
                    selected_assignments[trip_id].get(
                        "powertrain"
                    )
                    or ""
                )
                != str(
                    candidate_assignments[trip_id].get(
                        "powertrain"
                    )
                    or ""
                )
            )
            if exchanged_trip_ids:
                exchange_candidate_count_by_case[case] += 1
            exchange_rows.append(
                {
                    "case": case,
                    "candidate_hash": candidate_hash,
                    "feasible": row.get("feasible"),
                    "stage2_actual_canonical_cost_jpy": row.get(
                        "stage2_actual_canonical_cost_jpy"
                    ),
                    "powertrain_exchange_trip_count": len(
                        exchanged_trip_ids
                    ),
                    "powertrain_exchange_trip_ids": json.dumps(
                        exchanged_trip_ids,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )

        overlap_records = [
            dict(item)
            for item in list(
                selected.get("relaxed_pv_overlap_by_bev_duty") or ()
            )
            if isinstance(item, Mapping)
        ]
        selected_bev_ids = {
            str(item.get("vehicle_id") or "")
            for item in selected_assignments.values()
            if str(item.get("powertrain") or "").upper()
            in POWERTRAIN_ELECTRIC
        }
        overlap_vehicle_ids = {
            str(item.get("vehicle_id") or "")
            for item in overlap_records
        }
        selected_overlap_complete_by_case[case] = bool(
            selected_bev_ids
            and selected_bev_ids == overlap_vehicle_ids
        )
        for item in overlap_records:
            duty_overlap_rows.append(
                {
                    "case": case,
                    "vehicle_id": item.get("vehicle_id"),
                    "duty_ids": json.dumps(
                        list(item.get("duty_ids") or ()),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "home_depot_id": item.get("home_depot_id"),
                    "relaxed_positive_charge_slots": json.dumps(
                        list(
                            item.get(
                                "relaxed_positive_charge_slots"
                            )
                            or ()
                        ),
                        separators=(",", ":"),
                    ),
                    "relaxed_charge_input_kwh": item.get(
                        "relaxed_charge_input_kwh"
                    ),
                    "pv_available_in_relaxed_charge_slots_kwh": (
                        item.get(
                            "pv_available_in_relaxed_charge_slots_kwh"
                        )
                    ),
                    "semantics": item.get("semantics"),
                }
            )
    _write_csv(
        output_dir
        / "same_assignment_bev_ice_exchange_candidates.csv",
        [
            "case",
            "candidate_hash",
            "feasible",
            "stage2_actual_canonical_cost_jpy",
            "powertrain_exchange_trip_count",
            "powertrain_exchange_trip_ids",
        ],
        exchange_rows,
    )
    _write_csv(
        output_dir / "same_assignment_bev_duty_pv_overlap.csv",
        [
            "case",
            "vehicle_id",
            "duty_ids",
            "home_depot_id",
            "relaxed_positive_charge_slots",
            "relaxed_charge_input_kwh",
            "pv_available_in_relaxed_charge_slots_kwh",
            "semantics",
        ],
        duty_overlap_rows,
    )

    sunny_recourse_hash = _nested(
        sunny_settings,
        "stage1_time_indexed_energy_recourse_configuration",
        "objective_coefficient_and_rhs_hash",
    )
    rain_recourse_hash = _nested(
        rain_settings,
        "stage1_time_indexed_energy_recourse_configuration",
        "objective_coefficient_and_rhs_hash",
    )
    checks = {
        "pv_profile_hashes_differ": (
            sunny_manifest.get("pv_profile_hash")
            != rain_manifest.get("pv_profile_hash")
        ),
        "stage1_recourse_hashes_differ": (
            bool(sunny_recourse_hash)
            and bool(rain_recourse_hash)
            and sunny_recourse_hash != rain_recourse_hash
        ),
        "arbitrary_weather_bias_disabled": all(
            _nested(
                settings,
                "stage1_time_indexed_energy_recourse_configuration",
                "arbitrary_weather_assignment_bias_used",
            )
            is False
            for settings in (sunny_settings, rain_settings)
        ),
        "stage1_selected_recourse_objectives_differ": (
            selected_recourse_objective_by_case["sunny"] is not None
            and selected_recourse_objective_by_case["rain"] is not None
            and abs(
                float(
                    selected_recourse_objective_by_case["sunny"]
                )
                - float(
                    selected_recourse_objective_by_case["rain"]
                )
            )
            > 1.0e-9
        ),
        "sunny_twenty_alternatives_evaluated": (
            len(alternatives_by_case["sunny"]) >= 20
        ),
        "rain_twenty_alternatives_evaluated": (
            len(alternatives_by_case["rain"]) >= 20
        ),
        "sunny_twenty_feasible_alternatives_costed": (
            len(feasible_alternatives_by_case["sunny"]) >= 20
        ),
        "rain_twenty_feasible_alternatives_costed": (
            len(feasible_alternatives_by_case["rain"]) >= 20
        ),
        "sunny_selected_assignment_has_minimum_actual_cost": (
            selected_is_minimum_by_case["sunny"]
        ),
        "rain_selected_assignment_has_minimum_actual_cost": (
            selected_is_minimum_by_case["rain"]
        ),
        "sunny_candidate_assignments_recorded": (
            assignment_details_complete_by_case["sunny"]
        ),
        "rain_candidate_assignments_recorded": (
            assignment_details_complete_by_case["rain"]
        ),
        "sunny_bev_duty_pv_overlap_recorded": (
            selected_overlap_complete_by_case["sunny"]
        ),
        "rain_bev_duty_pv_overlap_recorded": (
            selected_overlap_complete_by_case["rain"]
        ),
        "sunny_bev_ice_exchange_candidates_enumerated": (
            exchange_candidate_count_by_case["sunny"] > 0
        ),
        "rain_bev_ice_exchange_candidates_enumerated": (
            exchange_candidate_count_by_case["rain"] > 0
        ),
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    payload = {
        "schema_version": "same_assignment_investigation_v1",
        "accepted": not failed,
        "checks": checks,
        "failed_checks": failed,
        "sunny_pv_profile_hash": sunny_manifest.get("pv_profile_hash"),
        "rain_pv_profile_hash": rain_manifest.get("pv_profile_hash"),
        "sunny_stage1_recourse_hash": sunny_recourse_hash,
        "rain_stage1_recourse_hash": rain_recourse_hash,
        "sunny_selected_recourse_objective_jpy": (
            selected_recourse_objective_by_case["sunny"]
        ),
        "rain_selected_recourse_objective_jpy": (
            selected_recourse_objective_by_case["rain"]
        ),
        "sunny_selected_is_minimum_actual_cost": (
            selected_is_minimum_by_case["sunny"]
        ),
        "rain_selected_is_minimum_actual_cost": (
            selected_is_minimum_by_case["rain"]
        ),
        "sunny_bev_ice_exchange_candidate_count": (
            exchange_candidate_count_by_case["sunny"]
        ),
        "rain_bev_ice_exchange_candidate_count": (
            exchange_candidate_count_by_case["rain"]
        ),
        "sunny_alternative_assignment_count": len(
            alternatives_by_case["sunny"]
        ),
        "rain_alternative_assignment_count": len(
            alternatives_by_case["rain"]
        ),
        "sunny_feasible_alternative_count": len(
            feasible_alternatives_by_case["sunny"]
        ),
        "rain_feasible_alternative_count": len(
            feasible_alternatives_by_case["rain"]
        ),
        "conclusion": (
            "same assignment audit satisfied"
            if not failed
            else "same assignment remains unresolved; formal completion blocked"
        ),
    }
    _write_json(output_dir / "same_assignment_investigation.json", payload)
    md = [
        "# Same-assignment investigation",
        "",
        f"- Accepted: `{str(payload['accepted']).lower()}`",
        f"- Sunny alternatives: `{payload['sunny_alternative_assignment_count']}`",
        f"- Rain alternatives: `{payload['rain_alternative_assignment_count']}`",
        (
            "- Sunny feasible alternatives: "
            f"`{payload['sunny_feasible_alternative_count']}`"
        ),
        (
            "- Rain feasible alternatives: "
            f"`{payload['rain_feasible_alternative_count']}`"
        ),
        "",
        "## Checks",
        "",
        *[
            f"- {name}: `{'PASS' if passed else 'FAIL'}`"
            for name, passed in checks.items()
        ],
        "",
    ]
    (output_dir / "same_assignment_investigation.md").write_text(
        "\n".join(md),
        encoding="utf-8",
    )
    return payload


def _build_pair_control_audit(
    *,
    sunny_dir: Path,
    rain_dir: Path,
    pair_manifest: Mapping[str, Any],
    assignment: Mapping[str, Any],
    same_assignment: Mapping[str, Any] | None,
    optimization_experiment_case: str = "phase3_baseline",
) -> dict[str, Any]:
    sunny = _read_json(sunny_dir / "comparison_case_manifest.json")
    rain = _read_json(rain_dir / "comparison_case_manifest.json")
    sunny_control = dict(sunny.get("comparison_control_payload") or {})
    rain_control = dict(rain.get("comparison_control_payload") or {})
    sunny_kpi = _read_json(sunny_dir / "kpi_summary.json")
    rain_kpi = _read_json(rain_dir / "kpi_summary.json")
    sunny_pv_source = _read_json_optional(sunny_dir / "pv_profile_source.json") or {}
    rain_pv_source = _read_json_optional(rain_dir / "pv_profile_source.json") or {}
    required_controls = (
        "service_date",
        "service_id",
        "trip_input_hash",
        "scenario_fleet_contract_hash",
        "active_vehicle_id_hash",
        "vehicle_parameter_hash",
        "initial_state_hash",
        "initial_soc_input_hash",
        "charger_configuration_hash",
        "non_pv_depot_asset_hash",
        "price_slot_hash",
        "bev_terminal_soc_policy",
        "bess_terminal_policy",
        "timestep_min",
        "day_ahead_solver_controls",
        "rolling_solver_controls",
        "git_sha",
    )
    controls = {
        key: {
            "sunny": sunny_control.get(key),
            "rain": rain_control.get(key),
            "match": (
                sunny_control.get(key) == rain_control.get(key)
                and sunny_control.get(key) is not None
            ),
        }
        for key in required_controls
    }
    sunny_pv = _number(sunny_kpi.get("pv_generation_kwh"))
    rain_pv = _number(rain_kpi.get("pv_generation_kwh"))
    sunny_expected_pv = _number(
        sunny_pv_source.get("expected_pv_generation_kwh")
    )
    rain_expected_pv = _number(
        rain_pv_source.get("expected_pv_generation_kwh")
    )
    if sunny_expected_pv is None:
        sunny_expected_pv = EXPECTED_PV_KWH["sunny"]
    if rain_expected_pv is None:
        rain_expected_pv = EXPECTED_PV_KWH["rain"]
    day_ahead_control_fields = (
        "time_limit_seconds_effective",
        "mip_gap_requested_ratio",
        "stage1_best_obj_stop_enabled",
        "gurobi_threads",
        "stage1_stage2_candidate_limit",
        "stage1_composition_search_radius",
        "random_seed",
    )
    if not optimization_experiment_case.startswith("phase4_"):
        day_ahead_control_fields += (
            "stage1_time_limit_seconds_requested",
            "stage2_time_limit_seconds_requested",
        )
    else:
        day_ahead_control_fields += (
            "phase4_phase3_seed_enabled",
            "phase4_phase3_seed_time_limit_sec",
            "phase4_phase3_seed_stage1_time_limit_sec",
            "phase4_phase3_seed_stage2_time_limit_sec",
            "phase4_phase3_seed_candidate_limit",
            "phase4_phase3_seed_composition_search_radius",
            "phase4_phase3_seed_search_directionality",
            "phase4_phase3_seed_bev_frontier_enabled",
            "phase4_integrated_seed_recourse_preflight_enabled",
            "phase4_integrated_seed_recourse_time_limit_sec",
            "phase4_total_solver_time_budget_sec",
        )
    rolling_control_fields = (
        "gurobi_threads",
        "mip_gap",
        "time_limit_sec",
        "random_seed",
        "execution_minutes",
    )

    def _control_section_complete(
        control: Mapping[str, Any],
        section_name: str,
        required_fields: Iterable[str],
    ) -> bool:
        section = control.get(section_name)
        return (
            isinstance(section, Mapping)
            and all(
                field in section and section.get(field) is not None
                for field in required_fields
            )
        )

    assignment_resolved = (
        assignment.get("assignment_hashes_equal") is False
        or (
            same_assignment is not None
            and same_assignment.get("accepted") is True
        )
    )
    checks = {
        "all_required_controls_match": all(
            item["match"] for item in controls.values()
        ),
        "day_ahead_solver_controls_complete": (
            _control_section_complete(
                sunny_control,
                "day_ahead_solver_controls",
                day_ahead_control_fields,
            )
            and _control_section_complete(
                rain_control,
                "day_ahead_solver_controls",
                day_ahead_control_fields,
            )
        ),
        "rolling_solver_controls_complete": (
            _control_section_complete(
                sunny_control,
                "rolling_solver_controls",
                rolling_control_fields,
            )
            and _control_section_complete(
                rain_control,
                "rolling_solver_controls",
                rolling_control_fields,
            )
        ),
        "comparison_control_hash_matches": (
            sunny.get("comparison_control_hash")
            == rain.get("comparison_control_hash")
            and bool(sunny.get("comparison_control_hash"))
        ),
        "pv_profile_hashes_differ": (
            sunny.get("pv_profile_hash") != rain.get("pv_profile_hash")
            and bool(sunny.get("pv_profile_hash"))
            and bool(rain.get("pv_profile_hash"))
        ),
        "sunny_expected_pv_total": (
            sunny_pv is not None
            and abs(sunny_pv - sunny_expected_pv) <= 1.0e-6
        ),
        "rain_expected_pv_total": (
            rain_pv is not None
            and abs(rain_pv - rain_expected_pv) <= 1.0e-6
        ),
        "pair_manifest_accepted": (
            pair_manifest.get(
                "accepted_for_controlled_pv_sensitivity_comparison"
            )
            is True
        ),
        "pair_formal_research_submission_ready": (
            pair_manifest.get("formal_research_submission_ready") is True
        ),
        "assignment_difference_or_strict_audit": assignment_resolved,
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    return {
        "accepted": not failed,
        "checks": checks,
        "failed_checks": failed,
        "controls": controls,
        "sunny_pv_generation_kwh": sunny_pv,
        "rain_pv_generation_kwh": rain_pv,
        "sunny_expected_pv_generation_kwh": sunny_expected_pv,
        "rain_expected_pv_generation_kwh": rain_expected_pv,
        "sunny_pv_profile_hash": sunny.get("pv_profile_hash"),
        "rain_pv_profile_hash": rain.get("pv_profile_hash"),
        "comparison_control_hash": sunny.get("comparison_control_hash"),
    }


def _run_pair_builder(
    *,
    sunny_dir: Path,
    rain_dir: Path,
    pair_dir: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "build_frontend_pv_pair_manifest.py"),
        "--baseline-run",
        str(sunny_dir),
        "--counterfactual-run",
        str(rain_dir),
        "--output-dir",
        str(pair_dir),
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    execution = {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "completed_at_utc": _utc_now(),
    }
    _write_json(pair_dir / "pair_builder_execution.json", execution)
    return execution


def _run_small_integrated_oracle(
    *,
    name: str,
    scenario_id: str,
    prepared_input_id: str,
    case_dir: Path,
    depot_id: str,
    service_id: str,
) -> dict[str, Any]:
    """Run the repository's bounded Phase 3 versus Phase 4 oracle.

    This subprocess is diagnostic only.  It never replaces the completed BFF
    full-scale run, and its output carries the oracle script's explicit
    small-subset scope warning.
    """

    output_path = case_dir / "small_integrated_oracle.json"
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "audit_small_integrated_weather_milp.py"),
        "--scenario-id",
        scenario_id,
        "--prepared-input-id",
        prepared_input_id,
        "--output",
        str(output_path),
        "--depot-id",
        depot_id,
        "--service-id",
        service_id,
        "--trip-count",
        "10",
        "--vehicles-per-type",
        "5",
        "--time-limit-sec",
        "120",
        "--random-seed",
        "42",
        "--skip-five-minute",
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    payload = _read_json_optional(output_path)
    primary = dict(payload.get("primary_comparison") or {})
    checks = {
        "process_completed": completed.returncode == 0,
        "artifact_created": bool(payload),
        "integrated_exact_oracle_eligible": (
            primary.get("integrated_exact_oracle_eligible") is True
        ),
        "two_stage_comparison_available": (
            primary.get("two_stage_comparison_available") is True
        ),
        "two_stage_matches_integrated_cost": (
            primary.get("two_stage_matches_integrated_cost") is True
        ),
        "used_vehicle_type_mix_matches": (
            primary.get("used_vehicle_type_mix_matches") is True
        ),
        "served_trip_type_mix_matches": (
            primary.get("served_trip_type_mix_matches") is True
        ),
        "assignment_powertrain_hash_matches": (
            primary.get("assignment_powertrain_hash_matches") is True
        ),
        "comparison_lower_bound_consistent": (
            primary.get("comparison_lower_bound_consistent") is True
        ),
    }
    audit = {
        "schema_version": "small_integrated_oracle_execution_audit_v1",
        "case": name,
        "purpose": (
            "bounded Phase 3 weather-coupled versus Phase 4 integrated oracle"
        ),
        "not_full_scale_evidence": True,
        "command": command,
        "returncode": completed.returncode,
        "runtime_sec": time.monotonic() - started,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "checks": checks,
        "failed_checks": sorted(
            key for key, passed in checks.items() if not passed
        ),
        "primary_comparison": primary,
        "output_path": str(output_path.resolve()),
    }
    _write_json(case_dir / "small_integrated_oracle_execution.json", audit)
    return audit


def _write_execution_log(
    output_dir: Path,
    events: list[dict[str, Any]],
    completion: Mapping[str, Any],
) -> None:
    lines = [
        "# Frontend controlled PV pair execution log",
        "",
        f"- Final status: `{completion.get('status')}`",
        f"- Frozen Git SHA: `{completion.get('frozen_git_sha')}`",
        "",
        "## Events",
        "",
        *_markdown_table(
            ["UTC", "Event", "Case/job", "Status", "Detail"],
            (
                (
                    event.get("timestamp_utc"),
                    event.get("event"),
                    event.get("case") or event.get("job_id"),
                    event.get("status"),
                    event.get("message") or event.get("detail"),
                )
                for event in events
            ),
        ),
        "",
        "## Remaining blockers",
        "",
        *[
            f"- {blocker}"
            for blocker in list(completion.get("failed_checks") or ())
        ],
        "",
    ]
    (output_dir / "execution_log.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _zip_directory(output_dir: Path) -> Path:
    zip_path = Path(f"{output_dir}.zip")
    temporary_zip_path = zip_path.with_suffix(f"{zip_path.suffix}.tmp")
    if zip_path.exists():
        raise RuntimeError(f"Evidence ZIP already exists: {zip_path}")
    if temporary_zip_path.exists():
        raise RuntimeError(
            f"Temporary evidence ZIP already exists: {temporary_zip_path}"
        )
    try:
        with zipfile.ZipFile(
            temporary_zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for path in sorted(output_dir.rglob("*")):
                if path.is_file():
                    archive.write(
                        path,
                        arcname=(
                            Path(output_dir.name)
                            / path.relative_to(output_dir)
                        ).as_posix(),
                    )
        if (
            not temporary_zip_path.is_file()
            or temporary_zip_path.stat().st_size <= 0
        ):
            raise RuntimeError(
                f"Failed to build evidence ZIP: {temporary_zip_path}"
            )
        with zipfile.ZipFile(temporary_zip_path, "r") as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise RuntimeError(
                    f"Evidence ZIP CRC validation failed: {bad_member}"
                )
        temporary_zip_path.replace(zip_path)
    except Exception:
        temporary_zip_path.unlink(missing_ok=True)
        raise
    return zip_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--sunny-scenario-id", required=True)
    parser.add_argument("--rain-scenario-id", required=True)
    parser.add_argument("--service-date", required=True)
    parser.add_argument("--rain-pv-source-date", required=True)
    parser.add_argument("--depot-id", required=True)
    parser.add_argument("--service-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--grid-energy-price-yen-per-kwh",
        type=float,
        default=None,
        help=(
            "Apply one explicit 00:00--24:00 grid-energy price to both "
            "cases. Must be supplied together with --demand-charge-yen-per-kw."
        ),
    )
    parser.add_argument(
        "--demand-charge-yen-per-kw",
        type=float,
        default=None,
        help=(
            "Apply the same demand/basic-charge coefficient to both cases. "
            "Use 0 to remove the model demand-charge cost term."
        ),
    )
    parser.add_argument(
        "--pv-capacity-kw",
        type=float,
        default=None,
        help=(
            "Apply one explicit positive PV rated output to both cases. "
            "When omitted, each frontend asset's explicit rated output is "
            "retained; legacy assets fall back to their area estimate."
        ),
    )
    parser.add_argument(
        "--allow-frontend-pv-capacity-override",
        action="store_true",
        help=(
            "Acknowledge that --pv-capacity-kw intentionally replaces the "
            "rated output saved in each frontend scenario. Omit both options "
            "to keep the frontend value authoritative."
        ),
    )
    parser.add_argument(
        "--optimization-experiment-case",
        choices=(
            "phase3_baseline",
            "phase3_bev_frontier",
            "phase4_integrated_actual_cost",
            "phase4_maximum_ev_utilization",
            "phase4_cost_constrained_ev_utilization",
        ),
        default="phase3_baseline",
        help=(
            "Select the unchanged Phase-3 baseline, the used-BEV >= K "
            "frontier, integrated accounting-cost Phase 4, maximum-EV "
            "lexicographic Phase 4, or its cost-constrained variant."
        ),
    )
    parser.add_argument(
        "--actual-cost-upper-bound-jpy",
        type=float,
        default=None,
        help=(
            "Absolute canonical operating-cost cap for the cost-constrained "
            "EV-utilization case. Derive it from a separately evidenced "
            "Phase-4 actual-cost optimum C*."
        ),
    )
    parser.add_argument(
        "--actual-cost-upper-bound-delta-percent",
        type=float,
        default=None,
        help=(
            "Recorded epsilon percentage used to derive the absolute cap; "
            "accepted values for the declared experiment are 0, 1, 3, 5, 10."
        ),
    )
    parser.add_argument(
        "--vehicle-usage-cost-semantics",
        choices=(
            "unclassified",
            "fixed_vehicle_day_cost",
            "driver_cost_proxy",
            "provisional_sensitivity",
        ),
        default="unclassified",
        help=(
            "Declare what the persisted per-used-bus-day coefficient means. "
            "A positive unclassified or provisional coefficient blocks an "
            "economic research claim."
        ),
    )
    parser.add_argument(
        "--job-timeout-seconds",
        type=float,
        default=14_400.0,
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=5.0,
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    _validate_pv_capacity_override_request(
        pv_capacity_kw=args.pv_capacity_kw,
        allow_frontend_pv_capacity_override=(
            args.allow_frontend_pv_capacity_override
        ),
    )
    if args.optimization_experiment_case == (
        "phase4_cost_constrained_ev_utilization"
    ):
        if (
            args.actual_cost_upper_bound_jpy is None
            or not math.isfinite(args.actual_cost_upper_bound_jpy)
            or args.actual_cost_upper_bound_jpy < 0.0
        ):
            raise ValueError(
                "cost-constrained EV utilization requires a nonnegative "
                "finite --actual-cost-upper-bound-jpy"
            )
        if args.actual_cost_upper_bound_delta_percent not in {
            0.0,
            1.0,
            3.0,
            5.0,
            10.0,
        }:
            raise ValueError(
                "--actual-cost-upper-bound-delta-percent must be one of "
                "0, 1, 3, 5, 10"
            )
    tariff_condition = _uniform_tariff_condition(
        grid_energy_price_yen_per_kwh=args.grid_energy_price_yen_per_kwh,
        demand_charge_yen_per_kw=args.demand_charge_yen_per_kw,
    )
    output_dir = args.output_dir.resolve()
    zip_path = Path(f"{output_dir}.zip")
    if output_dir.exists() or zip_path.exists():
        raise RuntimeError(
            "Refusing to overwrite an existing experiment directory or ZIP: "
            f"{output_dir}; {zip_path}"
        )
    frozen_sha = _assert_clean_frozen_repository()
    output_dir.mkdir(parents=True)
    events: list[dict[str, Any]] = []
    (output_dir / "frozen_git_sha.txt").write_text(
        frozen_sha + "\n",
        encoding="utf-8",
    )
    client = HttpJsonClient(args.base_url)
    health, health_raw = client.request_json("GET", "/health")
    _write_raw_json_response(output_dir / "bff_health_response.json", health_raw)
    if health.get("status") != "ok":
        raise RuntimeError(f"BFF health check failed: {health}")
    comparison_name = "same-service-date high-PV/low-PV supply sensitivity"
    if tariff_condition["override_requested"]:
        comparison_name += (
            " under a uniform "
            f"{tariff_condition['grid_energy_price_yen_per_kwh']:g} "
            "JPY/kWh grid tariff and "
            f"{tariff_condition['demand_charge_yen_per_kw']:g} JPY/kW "
            "demand-charge rate"
        )
    code_and_environment = {
        "schema_version": "controlled_pv_pair_environment_v3",
        "captured_at_utc": _utc_now(),
        "repository_root": str(REPO_ROOT),
        "frozen_git_sha": frozen_sha,
        "git_status_porcelain": _git("status", "--porcelain"),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "base_url": args.base_url,
        "bff_health": health,
        "gurobi_license_file": os.environ.get("GRB_LICENSE_FILE"),
        "mc_outputs_dir": os.environ.get("MC_OUTPUTS_DIR"),
        "bff_opt_executor": os.environ.get("BFF_OPT_EXECUTOR"),
        "comparison_name": comparison_name,
        "tariff_condition": tariff_condition,
        "pv_capacity_kw": args.pv_capacity_kw,
        "allow_frontend_pv_capacity_override": (
            args.allow_frontend_pv_capacity_override
        ),
        "optimization_experiment_case": (
            args.optimization_experiment_case
        ),
        "vehicle_usage_cost_semantics": (
            args.vehicle_usage_cost_semantics
        ),
        "pv_curve_delivery": (
            "Each Prepare request carries a date-specific, explicitly "
            "materialized depot-energy asset generated from the frontend "
            "asset's selected PV rated output and the repository's derived "
            "PV capacity-factor profile."
        ),
        "runtime_comparison_repetitions_per_case": 1,
        "runtime_claim_eligible": False,
    }
    _write_json(
        output_dir / "code_and_environment.json",
        code_and_environment,
    )
    _write_json(output_dir / "tariff_condition.json", tariff_condition)

    cases = (
        (
            "sunny",
            args.sunny_scenario_id,
            (
                _expected_pv_kwh_for_capacity("sunny", args.pv_capacity_kw)
                if args.pv_capacity_kw is not None
                else None
            ),
            build_prepare_payload(
                depot_id=args.depot_id,
                service_id=args.service_id,
                service_date=args.service_date,
                pv_source_date=args.service_date,
                comparison_role="baseline",
                vehicle_usage_cost_semantics=(
                    args.vehicle_usage_cost_semantics
                ),
                grid_energy_price_yen_per_kwh=(
                    args.grid_energy_price_yen_per_kwh
                ),
                demand_charge_yen_per_kw=args.demand_charge_yen_per_kw,
            ),
        ),
        (
            "rain",
            args.rain_scenario_id,
            (
                _expected_pv_kwh_for_capacity("rain", args.pv_capacity_kw)
                if args.pv_capacity_kw is not None
                else None
            ),
            build_prepare_payload(
                depot_id=args.depot_id,
                service_id=args.service_id,
                service_date=args.service_date,
                pv_source_date=args.rain_pv_source_date,
                comparison_role="pv_curve_counterfactual",
                vehicle_usage_cost_semantics=(
                    args.vehicle_usage_cost_semantics
                ),
                grid_energy_price_yen_per_kwh=(
                    args.grid_energy_price_yen_per_kwh
                ),
                demand_charge_yen_per_kw=args.demand_charge_yen_per_kw,
            ),
        ),
    )
    case_results: dict[str, dict[str, Any]] = {}
    failed_checks: list[str] = []
    for name, scenario_id, expected_pv_kwh, prepare_payload in cases:
        events.append(
            {
                "timestamp_utc": _utc_now(),
                "event": "case_started",
                "case": name,
                "status": "running",
                "detail": scenario_id,
            }
        )
        try:
            attached_prepare_payload, pv_asset_context = (
                _attach_controlled_pv_asset_to_prepare_payload(
                    client=client,
                    scenario_id=scenario_id,
                    prepare_payload=prepare_payload,
                    expected_pv_kwh=expected_pv_kwh,
                    timeout_seconds=args.job_timeout_seconds,
                    pv_capacity_kw=args.pv_capacity_kw,
                )
            )
            events.append(
                {
                    "timestamp_utc": _utc_now(),
                    "event": "pv_asset_materialized",
                    "case": name,
                    "status": "ready",
                    "detail": {
                        "pv_profile_id": _nested(
                            pv_asset_context,
                            "pv_profile_source",
                            "pv_profile_id",
                        ),
                        "pv_generation_kwh": _nested(
                            pv_asset_context,
                            "pv_profile_source",
                            "pv_generation_kwh",
                        ),
                    },
                }
            )
            result = _execute_case(
                name=name,
                scenario_id=scenario_id,
                prepare_payload=attached_prepare_payload,
                client=client,
                output_dir=output_dir,
                timeout_seconds=args.job_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                frozen_sha=frozen_sha,
                log=events,
                pv_asset_context=pv_asset_context,
                optimization_experiment_case=(
                    args.optimization_experiment_case
                ),
                actual_cost_upper_bound_jpy=(
                    args.actual_cost_upper_bound_jpy
                ),
                actual_cost_upper_bound_delta_ratio=(
                    None
                    if args.actual_cost_upper_bound_delta_percent is None
                    else args.actual_cost_upper_bound_delta_percent / 100.0
                ),
            )
            case_results[name] = result
            events.append(
                {
                    "timestamp_utc": _utc_now(),
                    "event": "case_terminal",
                    "case": name,
                    "status": result.get("job_status"),
                    "detail": result.get("run_dir"),
                }
            )
            if result.get("job_status") != "completed":
                failed_checks.append(
                    f"{name}:frontend_job_not_completed"
                )
        except Exception as exc:
            failed_checks.append(
                f"{name}:execution_exception:{type(exc).__name__}:{exc}"
            )
            case_dir = output_dir / name
            case_dir.mkdir(parents=True, exist_ok=True)
            _write_json(
                case_dir / "case_execution_failure.json",
                {
                    "case": name,
                    "failed_at_utc": _utc_now(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            events.append(
                {
                    "timestamp_utc": _utc_now(),
                    "event": "case_terminal",
                    "case": name,
                    "status": "failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )

    pair_manifest: dict[str, Any] = {}
    assignment: dict[str, Any] = {}
    pair_control: dict[str, Any] = {}
    same_assignment: dict[str, Any] | None = None
    case_gate_audits: dict[str, Any] = {}
    small_oracle_audits: dict[str, Any] = {}
    both_completed = all(
        case_results.get(name, {}).get("job_status") == "completed"
        for name in ("sunny", "rain")
    )
    if both_completed:
        sunny_dir = output_dir / "sunny"
        rain_dir = output_dir / "rain"
        pair_dir = output_dir / "pair"
        scenario_id_by_case = {
            "sunny": args.sunny_scenario_id,
            "rain": args.rain_scenario_id,
        }
        for name, case_dir in (
            ("sunny", sunny_dir),
            ("rain", rain_dir),
        ):
            oracle_audit = _run_small_integrated_oracle(
                name=name,
                scenario_id=scenario_id_by_case[name],
                prepared_input_id=str(
                    case_results[name].get("prepared_input_id") or ""
                ),
                case_dir=case_dir,
                depot_id=args.depot_id,
                service_id=args.service_id,
            )
            small_oracle_audits[name] = oracle_audit
            failed_checks.extend(
                f"{name}:small_oracle:{check}"
                for check in oracle_audit["failed_checks"]
            )
        pair_execution = _run_pair_builder(
            sunny_dir=sunny_dir,
            rain_dir=rain_dir,
            pair_dir=pair_dir,
        )
        pair_manifest = _read_json_optional(
            pair_dir / "pair_manifest.json"
        )
        if pair_execution["returncode"] != 0:
            failed_checks.append(
                "pair:builder_failed:"
                + str(pair_execution.get("stderr") or "").strip()
            )
        assignment = _build_assignment_difference(
            output_dir=output_dir,
            sunny_dir=sunny_dir,
            rain_dir=rain_dir,
        )
        solver_rows = _build_solver_comparison(
            output_dir,
            sunny_dir,
            rain_dir,
        )
        _build_research_comparison(
            output_dir,
            sunny_dir,
            rain_dir,
            solver_rows,
        )
        if assignment.get("assignment_hashes_equal") is True:
            same_assignment = _build_same_assignment_investigation(
                output_dir=output_dir,
                sunny_dir=sunny_dir,
                rain_dir=rain_dir,
                assignment=assignment,
            )
        for name, case_dir in (
            ("sunny", sunny_dir),
            ("rain", rain_dir),
        ):
            prepare_response = dict(
                case_results[name].get("prepare_response") or {}
            )
            audit = _case_gate_audit(
                name=name,
                case_dir=case_dir,
                prepared_trip_count=int(
                    prepare_response.get("tripCount") or 0
                ),
                frozen_sha=frozen_sha,
                tariff_condition=tariff_condition,
                optimization_experiment_case=(
                    args.optimization_experiment_case
                ),
            )
            case_gate_audits[name] = audit
            failed_checks.extend(
                f"{name}:{check}" for check in audit["failed_checks"]
            )
        pair_control = _build_pair_control_audit(
            sunny_dir=sunny_dir,
            rain_dir=rain_dir,
            pair_manifest=pair_manifest,
            assignment=assignment,
            same_assignment=same_assignment,
            optimization_experiment_case=(
                args.optimization_experiment_case
            ),
        )
        _write_json(
            output_dir / "pair" / "pair_control_audit.json",
            pair_control,
        )
        failed_checks.extend(
            f"pair:{check}" for check in pair_control["failed_checks"]
        )
    else:
        failed_checks.append("pair:both_frontend_jobs_not_completed")

    ending_sha = _git("rev-parse", "HEAD")
    ending_status = _git("status", "--porcelain")
    if ending_sha != frozen_sha:
        failed_checks.append("repository:git_sha_changed_during_execution")
    if ending_status:
        failed_checks.append("repository:worktree_became_dirty_during_execution")

    completion = {
        "schema_version": "controlled_pv_pair_completion_audit_v1",
        "status": "READY" if not failed_checks else "BLOCKED",
        "frozen_git_sha": frozen_sha,
        "ending_git_sha": ending_sha,
        "ending_git_status_porcelain": ending_status,
        "failed_checks": sorted(set(failed_checks)),
        "case_gate_audits": case_gate_audits,
        "small_integrated_oracle_audits": small_oracle_audits,
        "pair_control_audit": pair_control,
        "assignment_audit": {
            key: assignment.get(key)
            for key in (
                "sunny_assignment_hash",
                "rain_assignment_hash",
                "assignment_hashes_equal",
                "changed_trip_count",
            )
        },
        "same_assignment_investigation": same_assignment,
        "tariff_condition": tariff_condition,
        "pair_manifest": {
            "accepted_for_controlled_pv_sensitivity_comparison": (
                pair_manifest.get(
                    "accepted_for_controlled_pv_sensitivity_comparison"
                )
            ),
            "formal_research_submission_ready": pair_manifest.get(
                "formal_research_submission_ready"
            ),
            "failed_checks": pair_manifest.get("failed_checks"),
        },
        "zip_created": True,
        "zip_path": str(Path(f"{output_dir}.zip").resolve()),
    }
    _write_json(output_dir / "completion_audit.json", completion)
    _write_execution_log(output_dir, events, completion)
    try:
        zip_path = _zip_directory(output_dir)
    except Exception as exc:
        completion["zip_created"] = False
        completion["status"] = "BLOCKED"
        completion["failed_checks"] = sorted(
            {
                *list(completion.get("failed_checks") or ()),
                f"package:evidence_zip_failed:{type(exc).__name__}:{exc}",
            }
        )
        _write_json(output_dir / "completion_audit.json", completion)
        _write_execution_log(output_dir, events, completion)
        print(
            f"[complete] BLOCKED evidence={output_dir} zip_error={exc}",
            flush=True,
        )
        return 2
    print(
        f"[complete] {completion['status']} evidence={output_dir} "
        f"zip={zip_path}",
        flush=True,
    )
    return 0 if completion["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
