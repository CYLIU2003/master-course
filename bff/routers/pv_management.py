"""
bff/routers/pv_management.py

PV/BESS configuration management API
Handles Solcast daily PV profiles and depot energy asset settings
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from bff.dependencies import require_built
from bff.errors import AppErrorCode, make_error
from bff.store import scenario_store as store
from src.optimization.common.solcast_pv_profiles import (
    inspect_csv_time_coverage,
    parse_utc_offset,
    _read_solcast_records,
    _build_daily_profile,
)
from src.optimization.common.pv_area import (
    DEFAULT_PERFORMANCE_RATIO,
    DEFAULT_PANEL_POWER_DENSITY_KW_M2,
    DEFAULT_USABLE_AREA_RATIO,
    estimate_depot_pv_area_from_capacity,
    estimate_depot_pv_from_area,
)

router = APIRouter(tags=["pv_management"])

# Default Solcast CSV paths by depot
_SOLCAST_CSV_PATHS = {
    "tsurumaki": Path("data/external/solcast_raw/tsurumaki_2025_08_60min.csv"),
    "meguro": Path("data/external/solcast_raw/meguro_2025_08_60min.csv"),
}

_DEFAULT_TIMEZONE = "+09:00"  # JST


class PvProfileGenerateRequest(BaseModel):
    depot_id: str
    target_date: str  # YYYY-MM-DD
    depot_area_m2: Optional[float] = Field(default=None, ge=0.0)
    pv_capacity_kw: Optional[float] = Field(default=None, ge=0.0)
    slot_minutes: int = 15
    timezone_offset: str = "+09:00"
    performance_ratio: float = Field(default=DEFAULT_PERFORMANCE_RATIO, gt=0.0)


class DepotEnergyAssetUpdate(BaseModel):
    depot_id: str
    depot_area_m2: Optional[float] = Field(default=None, ge=0.0)
    pv_enabled: bool = False
    pv_capacity_kw: Optional[float] = Field(default=None, ge=0.0)
    pv_source_type: str = "solcast_daily"  # "solcast_daily" | "synthetic" | "uploaded"
    pv_source_date: Optional[str] = None
    pv_generation_kwh_by_slot: Optional[List[float]] = None
    bess_enabled: bool = False
    bess_energy_kwh: float = 0.0
    bess_power_kw: float = 0.0
    bess_initial_soc_kwh: float = 0.0
    bess_soc_min_kwh: float = 0.0
    bess_soc_max_kwh: float = 0.0
    bess_charge_efficiency: float = 0.95
    bess_discharge_efficiency: float = 0.95


class DepotEnergyAssetsUpdateRequest(BaseModel):
    depot_assets: List[DepotEnergyAssetUpdate]


def _find_solcast_csv(depot_id: str) -> Path:
    """Find Solcast CSV file for depot."""
    csv_path = _SOLCAST_CSV_PATHS.get(depot_id)
    if csv_path is None or not csv_path.exists():
        raise HTTPException(
            status_code=404,
            detail=make_error(
                AppErrorCode.MISSING_ARTIFACT,
                f"Solcast CSV not found for depot '{depot_id}'",
            ),
        )
    return csv_path


def _depot_area_from_scenario(scenario: Dict[str, Any], depot_id: str) -> Optional[float]:
    for depot in scenario.get("depots") or []:
        if not isinstance(depot, dict):
            continue
        if str(depot.get("id") or depot.get("depot_id") or depot.get("depotId") or "") != depot_id:
            continue
        value = depot.get("depotAreaM2", depot.get("depot_area_m2"))
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
    return None


def _sync_scenario_overlay_depot_energy_assets(scenario: Dict[str, Any]) -> None:
    sim_cfg = scenario.get("simulation_config") or {}
    assets = sim_cfg.get("depot_energy_assets") or []
    overlay = scenario.get("scenario_overlay")
    if not isinstance(overlay, dict):
        overlay = {}
        scenario["scenario_overlay"] = overlay
    normalized: dict[str, dict[str, Any]] = {}
    for item in assets:
        if not isinstance(item, dict):
            continue
        depot_id = str(item.get("depot_id") or item.get("depotId") or "").strip()
        if not depot_id:
            continue
        normalized_item = dict(item)
        normalized_item["depot_id"] = depot_id
        normalized[depot_id] = normalized_item
    overlay["depot_energy_assets"] = normalized
    cost_coefficients = overlay.get("cost_coefficients")
    if not isinstance(cost_coefficients, dict):
        cost_coefficients = {}
        overlay["cost_coefficients"] = cost_coefficients
    # Keep the legacy summary flag consistent for the frontend.  The depot
    # asset remains the authoritative model input because PV is depot-specific.
    cost_coefficients["pv_enabled"] = any(
        bool(item.get("pv_enabled", item.get("pvEnabled", False)))
        for item in normalized.values()
    )


@router.get("/pv/available-dates")
def get_available_pv_dates(depot_id: str) -> Dict[str, Any]:
    """
    Get available PV dates from Solcast CSV for a depot.
    
    Args:
        depot_id: Depot identifier
    
    Returns:
        Available dates and date range information
    """
    csv_path = _find_solcast_csv(depot_id)
    
    try:
        info = inspect_csv_time_coverage(
            csv_path,
            timezone_offset=_DEFAULT_TIMEZONE,
            fallback_period_min=30,
        )
        
        return {
            "depot_id": depot_id,
            "csv_path": str(csv_path),
            "available_dates": info["available_dates"],
            "date_range": {
                "min": info["min_period_end"],
                "max": info["max_period_end"],
            },
            "record_count": info["record_count"],
            "time_column": info["time_column"],
            "irradiance_column": info["irradiance_column"],
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=make_error(
                AppErrorCode.INTERNAL_ERROR,
                f"Failed to inspect Solcast CSV: {str(e)}",
            ),
        )


@router.post("/scenarios/{scenario_id}/pv-profile/generate")
def generate_pv_profile(
    scenario_id: str,
    request: PvProfileGenerateRequest,
) -> Dict[str, Any]:
    """
    Generate PV profile for a specific date and save to scenario.
    
    Args:
        scenario_id: Scenario identifier
        request: PV generation request parameters
    
    Returns:
        Generated PV profile information
    """
    # Verify scenario exists
    try:
        scenario = store.get_scenario_document_shallow(scenario_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=make_error(
                AppErrorCode.SCENARIO_NOT_FOUND,
                f"Scenario '{scenario_id}' not found",
            ),
        )
    
    # Find Solcast CSV
    csv_path = _find_solcast_csv(request.depot_id)
    
    try:
        # Read Solcast records
        local_tz = parse_utc_offset(request.timezone_offset)
        records, time_col, irr_col = _read_solcast_records(
            csv_path,
            local_tz=local_tz,
            time_col=None,
            irradiance_col=None,
            fallback_period_min=30,
        )
        
        depot_area_m2 = (
            request.depot_area_m2
            if request.depot_area_m2 is not None
            else _depot_area_from_scenario(scenario, request.depot_id)
        )
        area_estimate = estimate_depot_pv_from_area(depot_area_m2)
        capacity_kw = (
            float(request.pv_capacity_kw)
            if request.pv_capacity_kw is not None
            else float(area_estimate.capacity_kw)
        )
        capacity_estimate = estimate_depot_pv_area_from_capacity(capacity_kw)

        # Build daily profile
        profile = _build_daily_profile(
            records,
            target_date=request.target_date,
            slot_minutes=request.slot_minutes,
            pv_capacity_kw=capacity_kw,
            performance_ratio=request.performance_ratio,
        )
        
        total_generation_kwh = sum(profile["pv_generation_kwh_by_slot"])
        
        # Update scenario
        _update_scenario_pv_profile(
            scenario,
            request.depot_id,
            request.target_date,
            area_estimate.depot_area_m2,
            capacity_estimate.required_installable_area_m2,
            capacity_estimate.estimated_depot_area_m2,
            capacity_kw,
            request.pv_capacity_kw is not None,
            request.performance_ratio,
            request.slot_minutes,
            profile["capacity_factor_by_slot"],
            profile["pv_generation_kwh_by_slot"],
        )
        
        # Save scenario
        store.replace_scenario_experiment_configuration(
            scenario_id,
            simulation_config=dict(scenario.get("simulation_config") or {}),
            scenario_overlay=scenario.get("scenario_overlay"),
        )
        
        return {
            "scenario_id": scenario_id,
            "depot_id": request.depot_id,
            "target_date": request.target_date,
            "depot_area_m2": area_estimate.depot_area_m2,
            "estimated_installable_area_m2": round(
                capacity_estimate.required_installable_area_m2,
                6,
            ),
            "estimated_depot_area_from_pv_capacity_m2": round(
                capacity_estimate.estimated_depot_area_m2,
                6,
            ),
            "pv_capacity_kw": round(capacity_kw, 6),
            "pv_capacity_input_mode": (
                "rated_output_manual"
                if request.pv_capacity_kw is not None
                else "depot_area_estimate"
            ),
            "usable_area_ratio": DEFAULT_USABLE_AREA_RATIO,
            "panel_power_density_kw_m2": DEFAULT_PANEL_POWER_DENSITY_KW_M2,
            "performance_ratio": request.performance_ratio,
            "slot_minutes": request.slot_minutes,
            "total_generation_kwh": round(total_generation_kwh, 2),
            "peak_generation_kw": round(max(
                kw / (request.slot_minutes / 60.0)
                for kw in profile["pv_generation_kwh_by_slot"]
            ), 2),
            "capacity_factor_avg": round(
                sum(profile["capacity_factor_by_slot"]) / len(profile["capacity_factor_by_slot"]),
                4
            ),
            "profile": profile,
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=make_error(
                AppErrorCode.INTERNAL_ERROR,
                f"Failed to generate PV profile: {str(e)}",
            ),
        )


@router.post("/scenarios/{scenario_id}/depot-assets/update")
def update_depot_energy_assets(
    scenario_id: str,
    request: DepotEnergyAssetsUpdateRequest,
) -> Dict[str, Any]:
    """
    Update depot energy assets (PV/BESS) configuration for a scenario.
    
    Args:
        scenario_id: Scenario identifier
        request: Depot assets update request
    
    Returns:
        Update confirmation
    """
    # Verify scenario exists
    try:
        scenario = store.get_scenario_document_shallow(scenario_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=make_error(
                AppErrorCode.SCENARIO_NOT_FOUND,
                f"Scenario '{scenario_id}' not found",
            ),
        )
    
    # Ensure simulation_config exists
    if "simulation_config" not in scenario or scenario["simulation_config"] is None:
        scenario["simulation_config"] = {}
    
    if "depot_energy_assets" not in scenario["simulation_config"]:
        scenario["simulation_config"]["depot_energy_assets"] = []
    
    # Update each depot asset
    for asset_update in request.depot_assets:
        _update_depot_asset(scenario, asset_update)
    
    # Save scenario
    store.replace_scenario_experiment_configuration(
        scenario_id,
        simulation_config=dict(scenario.get("simulation_config") or {}),
        scenario_overlay=scenario.get("scenario_overlay"),
    )
    
    return {
        "scenario_id": scenario_id,
        "updated_count": len(request.depot_assets),
        "depot_ids": [a.depot_id for a in request.depot_assets],
    }


def _update_scenario_pv_profile(
    scenario: Dict[str, Any],
    depot_id: str,
    target_date: str,
    depot_area_m2: Optional[float],
    installable_area_m2: float,
    estimated_depot_area_m2: float,
    pv_capacity_kw: float,
    pv_capacity_kw_manual_override: bool,
    performance_ratio: float,
    slot_minutes: int,
    capacity_factor_by_slot: List[float],
    pv_generation_kwh_by_slot: List[float],
) -> None:
    """Update scenario with PV profile."""
    if "simulation_config" not in scenario:
        scenario["simulation_config"] = {}
    
    sim_cfg = scenario["simulation_config"]
    
    if "depot_energy_assets" not in sim_cfg:
        sim_cfg["depot_energy_assets"] = []
    
    # Find or create depot asset entry
    depot_asset = next(
        (a for a in sim_cfg["depot_energy_assets"] if a.get("depot_id") == depot_id),
        None,
    )
    
    if depot_asset is None:
        depot_asset = {"depot_id": depot_id}
        sim_cfg["depot_energy_assets"].append(depot_asset)
    
    profile_id = f"{depot_id}_{target_date}_{slot_minutes}min"

    # Keep every persisted representation of the selected daily profile in
    # sync. Prepare may consume the date-indexed capacity-factor rows, while
    # the frontend summary reads the direct slot series.
    depot_asset["depot_area_m2"] = depot_area_m2
    depot_asset["usable_area_ratio"] = DEFAULT_USABLE_AREA_RATIO
    depot_asset["panel_power_density_kw_m2"] = DEFAULT_PANEL_POWER_DENSITY_KW_M2
    depot_asset["performance_ratio"] = performance_ratio
    depot_asset["estimated_installable_area_m2"] = round(installable_area_m2, 6)
    depot_asset["estimated_depot_area_from_pv_capacity_m2"] = round(
        estimated_depot_area_m2,
        6,
    )
    depot_asset["pv_enabled"] = pv_capacity_kw > 0.0
    depot_asset["pv_capacity_kw"] = pv_capacity_kw
    depot_asset["derived_pv_capacity_kw"] = round(pv_capacity_kw, 6)
    depot_asset["pv_capacity_kw_manual_override"] = pv_capacity_kw_manual_override
    depot_asset["pv_capacity_input_mode"] = (
        "rated_output_manual"
        if pv_capacity_kw_manual_override
        else "depot_area_estimate"
    )
    depot_asset["pv_source_type"] = "solcast_daily"
    depot_asset["pv_source_date"] = target_date
    depot_asset["pv_case_id"] = profile_id
    depot_asset["pv_profile_source"] = "derived_daily"
    depot_asset["pv_profile_dates"] = [target_date]
    depot_asset["pv_slot_minutes"] = slot_minutes
    depot_asset["capacity_factor_by_slot"] = capacity_factor_by_slot
    depot_asset["pv_generation_kwh_by_slot"] = pv_generation_kwh_by_slot
    depot_asset["pv_capacity_factor_by_date"] = [
        {
            "date": target_date,
            "slot_minutes": slot_minutes,
            "capacity_factor_by_slot": list(capacity_factor_by_slot),
        }
    ]
    depot_asset["pv_generation_kwh_by_date"] = [
        {
            "date": target_date,
            "slot_minutes": slot_minutes,
            "pv_generation_kwh_by_slot": list(pv_generation_kwh_by_slot),
        }
    ]
    sim_cfg["pv_profile_id"] = profile_id
    sim_cfg["weather_observation_date"] = target_date
    sim_cfg["weather_profile_source"] = profile_id
    _sync_scenario_overlay_depot_energy_assets(scenario)


def _update_depot_asset(
    scenario: Dict[str, Any],
    asset_update: DepotEnergyAssetUpdate,
) -> None:
    """Update a single depot asset in scenario."""
    sim_cfg = scenario["simulation_config"]
    
    # Find or create depot asset entry
    depot_asset = next(
        (a for a in sim_cfg["depot_energy_assets"] if a.get("depot_id") == asset_update.depot_id),
        None,
    )
    
    if depot_asset is None:
        depot_asset = {"depot_id": asset_update.depot_id}
        sim_cfg["depot_energy_assets"].append(depot_asset)
    
    area_estimate = estimate_depot_pv_from_area(asset_update.depot_area_m2)
    is_manual_capacity = asset_update.pv_capacity_kw is not None
    effective_capacity_kw = (
        float(asset_update.pv_capacity_kw)
        if is_manual_capacity
        else float(area_estimate.capacity_kw)
    )
    capacity_estimate = estimate_depot_pv_area_from_capacity(
        effective_capacity_kw,
        usable_area_ratio=area_estimate.usable_area_ratio,
        panel_power_density_kw_m2=area_estimate.panel_power_density_kw_m2,
    )

    # Update PV settings
    depot_asset["depot_area_m2"] = area_estimate.depot_area_m2
    depot_asset["usable_area_ratio"] = DEFAULT_USABLE_AREA_RATIO
    depot_asset["panel_power_density_kw_m2"] = DEFAULT_PANEL_POWER_DENSITY_KW_M2
    depot_asset["performance_ratio"] = DEFAULT_PERFORMANCE_RATIO
    depot_asset["estimated_installable_area_m2"] = round(
        capacity_estimate.required_installable_area_m2,
        6,
    )
    depot_asset["estimated_depot_area_from_pv_capacity_m2"] = round(
        capacity_estimate.estimated_depot_area_m2,
        6,
    )
    depot_asset["pv_enabled"] = effective_capacity_kw > 0.0
    depot_asset["pv_capacity_kw"] = round(effective_capacity_kw, 6)
    depot_asset["derived_pv_capacity_kw"] = round(effective_capacity_kw, 6)
    depot_asset["pv_capacity_kw_manual_override"] = is_manual_capacity
    depot_asset["pv_capacity_input_mode"] = (
        "rated_output_manual" if is_manual_capacity else "depot_area_estimate"
    )
    depot_asset["pv_source_type"] = asset_update.pv_source_type
    
    if asset_update.pv_source_date:
        depot_asset["pv_source_date"] = asset_update.pv_source_date
    
    if asset_update.pv_generation_kwh_by_slot:
        depot_asset["pv_generation_kwh_by_slot"] = asset_update.pv_generation_kwh_by_slot
    
    # Update BESS settings
    depot_asset["bess_enabled"] = asset_update.bess_enabled
    depot_asset["bess_energy_kwh"] = asset_update.bess_energy_kwh
    depot_asset["bess_power_kw"] = asset_update.bess_power_kw
    depot_asset["bess_initial_soc_kwh"] = asset_update.bess_initial_soc_kwh
    depot_asset["bess_soc_min_kwh"] = asset_update.bess_soc_min_kwh
    depot_asset["bess_soc_max_kwh"] = asset_update.bess_soc_max_kwh
    depot_asset["bess_charge_efficiency"] = asset_update.bess_charge_efficiency
    depot_asset["bess_discharge_efficiency"] = asset_update.bess_discharge_efficiency
    _sync_scenario_overlay_depot_energy_assets(scenario)
