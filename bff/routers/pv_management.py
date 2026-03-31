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
from pydantic import BaseModel

from bff.dependencies import require_built
from bff.errors import AppErrorCode, make_error
from bff.store import scenario_store as store
from src.optimization.common.solcast_pv_profiles import (
    inspect_csv_time_coverage,
    parse_utc_offset,
    _read_solcast_records,
    _build_daily_profile,
)

router = APIRouter(tags=["pv_management"])

# Default Solcast CSV paths by depot
_SOLCAST_CSV_PATHS = {
    "tsurumaki": Path("data/pv/tsurumaki_solcast.csv"),
    "meguro": Path("data/pv/meguro_solcast.csv"),
}

_DEFAULT_TIMEZONE = "+09:00"  # JST


class PvProfileGenerateRequest(BaseModel):
    depot_id: str
    target_date: str  # YYYY-MM-DD
    pv_capacity_kw: float
    slot_minutes: int = 15
    timezone_offset: str = "+09:00"


class DepotEnergyAssetUpdate(BaseModel):
    depot_id: str
    pv_enabled: bool = False
    pv_capacity_kw: float = 0.0
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
                AppErrorCode.RESOURCE_NOT_FOUND,
                f"Solcast CSV not found for depot '{depot_id}'",
            ),
        )
    return csv_path


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
        scenario = store.get_scenario(scenario_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=make_error(
                AppErrorCode.RESOURCE_NOT_FOUND,
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
        
        # Build daily profile
        profile = _build_daily_profile(
            records,
            target_date=request.target_date,
            slot_minutes=request.slot_minutes,
            pv_capacity_kw=request.pv_capacity_kw,
        )
        
        total_generation_kwh = sum(profile["pv_generation_kwh_by_slot"])
        
        # Update scenario
        _update_scenario_pv_profile(
            scenario,
            request.depot_id,
            request.target_date,
            request.pv_capacity_kw,
            profile["pv_generation_kwh_by_slot"],
        )
        
        # Save scenario
        store.save_scenario_document(scenario_id, scenario)
        
        return {
            "scenario_id": scenario_id,
            "depot_id": request.depot_id,
            "target_date": request.target_date,
            "pv_capacity_kw": request.pv_capacity_kw,
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
        scenario = store.get_scenario(scenario_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=make_error(
                AppErrorCode.RESOURCE_NOT_FOUND,
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
    store.save_scenario_document(scenario_id, scenario)
    
    return {
        "scenario_id": scenario_id,
        "updated_count": len(request.depot_assets),
        "depot_ids": [a.depot_id for a in request.depot_assets],
    }


def _update_scenario_pv_profile(
    scenario: Dict[str, Any],
    depot_id: str,
    target_date: str,
    pv_capacity_kw: float,
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
    
    # Update PV settings
    depot_asset["pv_enabled"] = True
    depot_asset["pv_capacity_kw"] = pv_capacity_kw
    depot_asset["pv_source_type"] = "solcast_daily"
    depot_asset["pv_source_date"] = target_date
    depot_asset["pv_generation_kwh_by_slot"] = pv_generation_kwh_by_slot


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
    
    # Update PV settings
    depot_asset["pv_enabled"] = asset_update.pv_enabled
    depot_asset["pv_capacity_kw"] = asset_update.pv_capacity_kw
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
