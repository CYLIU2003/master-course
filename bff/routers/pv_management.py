"""
bff/routers/pv_management.py

PV/BESS configuration management API
Handles Solcast daily PV profiles and depot energy asset settings
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    model_config = ConfigDict(allow_inf_nan=False)

    depot_id: str
    target_date: str  # YYYY-MM-DD
    depot_area_m2: Optional[float] = Field(default=None, ge=0.0)
    pv_capacity_kw: Optional[float] = Field(default=None, ge=0.0)
    slot_minutes: Literal[5, 15, 30, 60] = 15
    timezone_offset: str = "+09:00"
    performance_ratio: float = Field(
        default=DEFAULT_PERFORMANCE_RATIO,
        gt=0.0,
        le=1.0,
    )

    @field_validator("target_date")
    @classmethod
    def _validate_target_date(cls, value: str) -> str:
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise ValueError("target_date must use YYYY-MM-DD format") from exc


class DepotEnergyAssetUpdate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    depot_id: str = Field(min_length=1)
    depot_area_m2: Optional[float] = Field(default=None, ge=0.0)
    pv_enabled: bool = False
    pv_capacity_kw: Optional[float] = Field(default=None, ge=0.0)
    pv_source_type: Literal["solcast_daily", "synthetic", "uploaded"] = (
        "solcast_daily"
    )
    pv_source_date: Optional[str] = None
    pv_generation_kwh_by_slot: Optional[List[float]] = None
    bess_enabled: bool = False
    bess_energy_kwh: float = Field(default=0.0, ge=0.0)
    bess_power_kw: float = Field(default=0.0, ge=0.0)
    bess_initial_soc_kwh: float = Field(default=0.0, ge=0.0)
    bess_soc_min_kwh: float = Field(default=0.0, ge=0.0)
    bess_soc_max_kwh: float = Field(default=0.0, ge=0.0)
    bess_charge_efficiency: float = Field(default=0.95, gt=0.0, le=1.0)
    bess_discharge_efficiency: float = Field(default=0.95, gt=0.0, le=1.0)

    @field_validator("depot_id")
    @classmethod
    def _strip_depot_id(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("depot_id must not be blank")
        return normalized

    @field_validator("pv_source_date")
    @classmethod
    def _validate_optional_source_date(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise ValueError("pv_source_date must use YYYY-MM-DD format") from exc

    @field_validator("pv_generation_kwh_by_slot")
    @classmethod
    def _validate_generation_slots(
        cls,
        value: Optional[List[float]],
    ) -> Optional[List[float]]:
        if value is None:
            return None
        normalized = [float(item) for item in value]
        if any(not math.isfinite(item) or item < 0.0 for item in normalized):
            raise ValueError(
                "pv_generation_kwh_by_slot must contain finite non-negative values"
            )
        return normalized


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
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=make_error(
                AppErrorCode.SCHEMA_VALIDATION_ERROR,
                f"Invalid Solcast artifact: {str(e)}",
            ),
        ) from e
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

    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=make_error(
                AppErrorCode.SCHEMA_VALIDATION_ERROR,
                f"Invalid PV profile request: {str(e)}",
            ),
        ) from e
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
    try:
        for asset_update in request.depot_assets:
            _update_depot_asset(scenario, asset_update)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=make_error(
                AppErrorCode.SCHEMA_VALIDATION_ERROR,
                str(exc),
            ),
        ) from exc
    
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


def _generation_from_capacity_factors(
    capacity_factors: List[float],
    *,
    capacity_kw: float,
    slot_minutes: int,
) -> List[float]:
    duration_h = max(int(slot_minutes), 1) / 60.0
    return [
        round(max(float(capacity_kw), 0.0) * max(float(value), 0.0) * duration_h, 6)
        for value in capacity_factors
    ]


def _scale_generation_values(
    values: List[float],
    *,
    old_capacity_kw: float,
    new_capacity_kw: float,
) -> List[float]:
    if old_capacity_kw <= 0.0:
        return [] if new_capacity_kw > 0.0 else [0.0 for _ in values]
    ratio = max(float(new_capacity_kw), 0.0) / old_capacity_kw
    return [round(max(float(value), 0.0) * ratio, 6) for value in values]


def _rescale_persisted_pv_profiles(
    depot_asset: Dict[str, Any],
    *,
    old_capacity_kw: float,
    new_capacity_kw: float,
) -> None:
    slot_minutes = int(depot_asset.get("pv_slot_minutes") or 60)
    direct_factors = list(depot_asset.get("capacity_factor_by_slot") or [])
    direct_generation = list(depot_asset.get("pv_generation_kwh_by_slot") or [])
    if direct_factors:
        depot_asset["pv_generation_kwh_by_slot"] = _generation_from_capacity_factors(
            direct_factors,
            capacity_kw=new_capacity_kw,
            slot_minutes=slot_minutes,
        )
    elif direct_generation:
        depot_asset["pv_generation_kwh_by_slot"] = _scale_generation_values(
            direct_generation,
            old_capacity_kw=old_capacity_kw,
            new_capacity_kw=new_capacity_kw,
        )

    factor_rows = list(depot_asset.get("pv_capacity_factor_by_date") or [])
    if factor_rows:
        generation_rows: List[Dict[str, Any]] = []
        for row in factor_rows:
            if not isinstance(row, dict):
                continue
            factors = list(row.get("capacity_factor_by_slot") or [])
            row_slot_minutes = int(row.get("slot_minutes") or slot_minutes)
            generation_rows.append(
                {
                    "date": row.get("date"),
                    "slot_minutes": row_slot_minutes,
                    "pv_generation_kwh_by_slot": _generation_from_capacity_factors(
                        factors,
                        capacity_kw=new_capacity_kw,
                        slot_minutes=row_slot_minutes,
                    ),
                }
            )
        depot_asset["pv_generation_kwh_by_date"] = generation_rows
    else:
        scaled_rows: List[Dict[str, Any]] = []
        for row in list(depot_asset.get("pv_generation_kwh_by_date") or []):
            if not isinstance(row, dict):
                continue
            scaled = dict(row)
            scaled["pv_generation_kwh_by_slot"] = _scale_generation_values(
                list(row.get("pv_generation_kwh_by_slot") or []),
                old_capacity_kw=old_capacity_kw,
                new_capacity_kw=new_capacity_kw,
            )
            scaled_rows.append(scaled)
        if scaled_rows:
            depot_asset["pv_generation_kwh_by_date"] = scaled_rows


def _finite_float(
    value: Any,
    *,
    field_name: str,
    default: Optional[float] = None,
) -> float:
    if value is None and default is not None:
        return float(default)
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _validate_depot_asset(depot_asset: Dict[str, Any]) -> None:
    depot_id = str(depot_asset.get("depot_id") or "")
    pv_capacity_kw = _finite_float(
        depot_asset.get("pv_capacity_kw"),
        field_name=f"Depot {depot_id} PV capacity",
        default=0.0,
    )
    if pv_capacity_kw < 0.0:
        raise ValueError(
            f"Depot {depot_id} PV capacity must be finite and non-negative"
        )
    generation_series = [
        list(depot_asset.get("pv_generation_kwh_by_slot") or [])
    ]
    generation_series.extend(
        list(row.get("pv_generation_kwh_by_slot") or [])
        for row in list(depot_asset.get("pv_generation_kwh_by_date") or [])
        if isinstance(row, dict)
    )
    for value in (item for series in generation_series for item in series):
        if _finite_float(
            value,
            field_name=f"Depot {depot_id} PV generation",
        ) < 0.0:
            raise ValueError(
                f"Depot {depot_id} PV generation must be finite and non-negative"
            )
    capacity_factor_series = [
        list(depot_asset.get("capacity_factor_by_slot") or [])
    ]
    capacity_factor_series.extend(
        list(row.get("capacity_factor_by_slot") or [])
        for row in list(depot_asset.get("pv_capacity_factor_by_date") or [])
        if isinstance(row, dict)
    )
    for value in (
        item for series in capacity_factor_series for item in series
    ):
        factor = _finite_float(
            value,
            field_name=f"Depot {depot_id} PV capacity factor",
        )
        if not (0.0 <= factor <= 1.0):
            raise ValueError(
                f"Depot {depot_id} PV capacity factors must be within [0, 1]"
            )

    numeric_fields = (
        "bess_energy_kwh",
        "bess_power_kw",
        "bess_initial_soc_kwh",
        "bess_soc_min_kwh",
        "bess_soc_max_kwh",
    )
    values = {
        field_name: _finite_float(
            depot_asset.get(field_name),
            field_name=f"Depot {depot_id} {field_name}",
            default=0.0,
        )
        for field_name in numeric_fields
    }
    if any(value < 0.0 for value in values.values()):
        raise ValueError(f"Depot {depot_id} BESS values must be finite and non-negative")

    charge_efficiency = _finite_float(
        depot_asset.get("bess_charge_efficiency"),
        field_name=f"Depot {depot_id} BESS charge efficiency",
        default=0.95,
    )
    discharge_efficiency = _finite_float(
        depot_asset.get("bess_discharge_efficiency"),
        field_name=f"Depot {depot_id} BESS discharge efficiency",
        default=0.95,
    )
    if not (0.0 < charge_efficiency <= 1.0):
        raise ValueError(f"Depot {depot_id} BESS charge efficiency must be within (0, 1]")
    if not (0.0 < discharge_efficiency <= 1.0):
        raise ValueError(
            f"Depot {depot_id} BESS discharge efficiency must be within (0, 1]"
        )

    energy_kwh = values["bess_energy_kwh"]
    power_kw = values["bess_power_kw"]
    soc_min = values["bess_soc_min_kwh"]
    soc_max = values["bess_soc_max_kwh"]
    initial_soc = values["bess_initial_soc_kwh"]
    if soc_min > soc_max or soc_max > energy_kwh:
        raise ValueError(
            f"Depot {depot_id} BESS SOC bounds must satisfy 0 <= min <= max <= capacity"
        )
    if not (soc_min <= initial_soc <= soc_max):
        raise ValueError(
            f"Depot {depot_id} initial BESS SOC must be within [min, max]"
        )
    if bool(depot_asset.get("bess_enabled", False)) and (
        energy_kwh <= 0.0 or power_kw <= 0.0
    ):
        raise ValueError(
            f"Depot {depot_id} enabled BESS requires positive energy and power ratings"
        )


def _update_depot_asset(
    scenario: Dict[str, Any],
    asset_update: DepotEnergyAssetUpdate,
) -> None:
    """Patch one depot asset without resetting fields omitted by the caller."""
    sim_cfg = scenario.setdefault("simulation_config", {})
    assets = sim_cfg.setdefault("depot_energy_assets", [])
    depot_asset = next(
        (
            item
            for item in assets
            if str(item.get("depot_id") or "") == asset_update.depot_id
        ),
        None,
    )
    is_new = depot_asset is None
    if depot_asset is None:
        depot_asset = {"depot_id": asset_update.depot_id}
        assets.append(depot_asset)

    explicitly_set = set(asset_update.model_fields_set)
    if is_new:
        explicitly_set = set(type(asset_update).model_fields)

    old_capacity_kw = float(depot_asset.get("pv_capacity_kw") or 0.0)
    previous_manual_override = bool(
        depot_asset.get("pv_capacity_kw_manual_override", False)
    )
    area_value = (
        asset_update.depot_area_m2
        if "depot_area_m2" in explicitly_set
        else depot_asset.get("depot_area_m2")
    )
    area_estimate = estimate_depot_pv_from_area(area_value)

    capacity_touched = is_new or "pv_capacity_kw" in explicitly_set
    if "pv_capacity_kw" in explicitly_set:
        manual_override = asset_update.pv_capacity_kw is not None
        effective_capacity_kw = (
            float(asset_update.pv_capacity_kw)
            if manual_override
            else float(area_estimate.capacity_kw)
        )
    elif "depot_area_m2" in explicitly_set and not previous_manual_override:
        manual_override = False
        effective_capacity_kw = float(area_estimate.capacity_kw)
        capacity_touched = True
    else:
        manual_override = previous_manual_override
        effective_capacity_kw = old_capacity_kw

    geometry_touched = (
        is_new
        or "depot_area_m2" in explicitly_set
        or capacity_touched
    )
    if geometry_touched:
        capacity_estimate = estimate_depot_pv_area_from_capacity(
            effective_capacity_kw,
            usable_area_ratio=area_estimate.usable_area_ratio,
            panel_power_density_kw_m2=area_estimate.panel_power_density_kw_m2,
        )
        if is_new or "depot_area_m2" in explicitly_set:
            depot_asset["depot_area_m2"] = area_estimate.depot_area_m2
        depot_asset["usable_area_ratio"] = DEFAULT_USABLE_AREA_RATIO
        depot_asset["panel_power_density_kw_m2"] = (
            DEFAULT_PANEL_POWER_DENSITY_KW_M2
        )
        depot_asset.setdefault("performance_ratio", DEFAULT_PERFORMANCE_RATIO)
        depot_asset["estimated_installable_area_m2"] = round(
            capacity_estimate.required_installable_area_m2,
            6,
        )
        depot_asset["estimated_depot_area_from_pv_capacity_m2"] = round(
            capacity_estimate.estimated_depot_area_m2,
            6,
        )
        depot_asset["pv_capacity_kw"] = round(effective_capacity_kw, 6)
        depot_asset["derived_pv_capacity_kw"] = round(effective_capacity_kw, 6)
        depot_asset["pv_capacity_kw_manual_override"] = manual_override
        depot_asset["pv_capacity_input_mode"] = (
            "rated_output_manual" if manual_override else "depot_area_estimate"
        )

    if "pv_enabled" in explicitly_set:
        depot_asset["pv_enabled"] = bool(asset_update.pv_enabled)
    elif is_new:
        depot_asset["pv_enabled"] = effective_capacity_kw > 0.0

    if "pv_source_type" in explicitly_set:
        depot_asset["pv_source_type"] = asset_update.pv_source_type
    if "pv_source_date" in explicitly_set:
        if asset_update.pv_source_date is None:
            depot_asset.pop("pv_source_date", None)
        else:
            depot_asset["pv_source_date"] = asset_update.pv_source_date

    if "pv_generation_kwh_by_slot" in explicitly_set:
        depot_asset["pv_generation_kwh_by_slot"] = list(
            asset_update.pv_generation_kwh_by_slot or []
        )
        # A direct uploaded replacement has no date-indexed capacity-factor
        # provenance. Remove stale derived representations rather than mixing
        # curves from different capacities.
        depot_asset.pop("capacity_factor_by_slot", None)
        depot_asset.pop("pv_capacity_factor_by_date", None)
        depot_asset.pop("pv_generation_kwh_by_date", None)
    elif capacity_touched and not math.isclose(
        old_capacity_kw,
        effective_capacity_kw,
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        _rescale_persisted_pv_profiles(
            depot_asset,
            old_capacity_kw=old_capacity_kw,
            new_capacity_kw=effective_capacity_kw,
        )

    bess_fields = (
        "bess_enabled",
        "bess_energy_kwh",
        "bess_power_kw",
        "bess_initial_soc_kwh",
        "bess_soc_min_kwh",
        "bess_soc_max_kwh",
        "bess_charge_efficiency",
        "bess_discharge_efficiency",
    )
    for field_name in bess_fields:
        if field_name in explicitly_set:
            depot_asset[field_name] = getattr(asset_update, field_name)

    _validate_depot_asset(depot_asset)
    _sync_scenario_overlay_depot_energy_assets(scenario)
