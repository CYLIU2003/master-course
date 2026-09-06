from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


_DEFAULT_INPUT_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "docs" / "constant" / "input_template.json"


class TimeOfUseBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)
    price_per_kwh: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_clock_hour_range(self) -> "TimeOfUseBand":
        if self.start_hour >= self.end_hour:
            raise ValueError("start_hour must be earlier than end_hour")
        return self


class FleetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_bev: int = Field(default=0, ge=0)
    n_ice: int = Field(default=0, ge=0)


class ChargingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_simultaneous_sessions: Optional[int] = Field(default=None, ge=0)
    overnight_window_start: Optional[str] = None
    overnight_window_end: Optional[str] = None
    depot_power_limit_kw: Optional[float] = Field(default=None, ge=0.0)
    charger_power_limit_kw: Optional[float] = Field(default=None, ge=0.0)
    initial_soc_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    final_soc_floor_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    final_soc_target_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    final_soc_target_tolerance_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    charging_power_model: Literal[
        "constant_power_v0",
        "piecewise_soc_taper_v1",
    ] = "piecewise_soc_taper_v1"
    charge_setup_minutes: int = Field(default=5, ge=0)
    charge_teardown_minutes: int = Field(default=5, ge=0)
    minimum_charge_session_minutes: int = Field(default=15, ge=0)


class CostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tou_pricing: list[TimeOfUseBand] = Field(default_factory=list)
    grid_flat_price_per_kwh: float = Field(default=0.0, ge=0.0)
    grid_sell_price_per_kwh: float = Field(default=0.0, ge=0.0)
    demand_charge_cost_per_kw: float = Field(default=0.0, ge=0.0)
    vehicle_usage_cost_jpy_per_used_bus: float = Field(default=0.0, ge=0.0)
    vehicle_usage_cost_semantics: str = "unclassified"
    pv_marginal_charge_cost_yen_per_kwh: float = Field(default=0.0, ge=0.0)
    pv_curtail_penalty_yen_per_kwh: float = Field(default=0.0, ge=0.0)
    pv_enabled: bool = False
    pv_scale: float = Field(default=1.0, ge=0.0)
    diesel_price_per_l: float = Field(default=0.0, ge=0.0)
    ice_co2_kg_per_l: float = Field(default=2.64, ge=0.0)
    grid_co2_kg_per_kwh: float = Field(default=0.0, ge=0.0)
    co2_price_per_kg: float = Field(default=1.0, ge=0.0)
    co2_emissions_cap_kg: Optional[float] = Field(default=None, ge=0.0)
    co2_price_source: Optional[str] = None
    co2_reference_date: Optional[str] = None
    pv_profile_id: Optional[str] = None
    pv_input_semantics: Literal[
        "available_surplus_after_depot_load",
        "gross_generation_before_depot_load",
    ] = "available_surplus_after_depot_load"
    pv_resolution_minutes: int = Field(default=60, ge=1)
    weather_mode: Optional[str] = None
    weather_factor_scalar: Optional[float] = Field(default=None, ge=0.0)
    weather_factor_hourly: list[float] = Field(default_factory=list)


class SolverConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal[
        "milp",
        "alns",
        "hybrid",
        "ga",
        "abc",
        "thesis_mode",
        "debug_mode",
        "mode_milp_only",
        "mode_alns_only",
        "mode_ga_only",
        "mode_abc_only",
        "mode_hybrid",
        "mode_alns_milp",
        "phase1",
        "phase1_charging_only",
        "phase2",
        "phase2_assignment_only",
        "phase3",
        "phase3_two_stage",
        "phase4",
        "phase4_integrated",
        "diagnostic",
        "diagnostic_mode",
    ] = "hybrid"
    time_limit_seconds: int = Field(default=300, ge=1)
    mip_gap: float = Field(default=0.01, ge=0.0)
    alns_iterations: int = Field(default=500, ge=1)
    no_improvement_limit: int = Field(default=100, ge=1)
    destroy_fraction: float = Field(default=0.25, gt=0.0, le=1.0)
    objective_mode: Literal["total_cost", "co2", "balanced", "utilization"] = "total_cost"
    allow_partial_service: bool = False
    service_coverage_mode: Literal["strict", "penalized"] = "strict"
    unserved_penalty: float = Field(default=10000.0, ge=0.0)
    objective_weights: dict[str, float] = Field(default_factory=dict)
    objective_preset: Optional[str] = None
    trip_energy_model: Literal[
        "distance_average_v0",
        "literature_proxy_v1",
    ] = "distance_average_v0"
    trip_energy_sensitivity_scale: float = Field(default=1.0, ge=0.0)
    bev_trip_energy_sensitivity_scale: float = Field(default=1.0, ge=0.0)
    ice_trip_fuel_sensitivity_scale: float = Field(default=1.0, ge=0.0)
    fixed_route_band_mode: bool = False
    max_start_fragments_per_vehicle: int = Field(default=100, ge=1)
    max_end_fragments_per_vehicle: int = Field(default=100, ge=1)
    milp_max_successors_per_trip: Optional[int] = Field(default=None, ge=1)
    enable_vehicle_diagram_output: bool = False
    output_vehicle_diagram: bool = False
    termination_policy: Literal["time_limit_or_gap"] = "time_limit_or_gap"

    @model_validator(mode="after")
    def _normalize_vehicle_diagram_flags(self) -> "SolverConfig":
        # fixed_route_band_mode=True の場合もダイアグラム出力を自動有効化
        enabled = bool(
            self.enable_vehicle_diagram_output
            or self.output_vehicle_diagram
            or self.fixed_route_band_mode
        )
        self.enable_vehicle_diagram_output = enabled
        self.output_vehicle_diagram = enabled
        return self


class ScenarioOverlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    dataset_id: str
    dataset_version: str
    random_seed: int
    depot_ids: list[str] = Field(default_factory=list)
    route_ids: list[str] = Field(default_factory=list)
    depot_energy_assets: dict[str, dict[str, object]] = Field(default_factory=dict)
    fleet: FleetConfig = Field(default_factory=FleetConfig)
    charging_constraints: ChargingConfig = Field(default_factory=ChargingConfig)
    cost_coefficients: CostConfig = Field(default_factory=CostConfig)
    solver_config: SolverConfig = Field(default_factory=SolverConfig)


def _parse_local_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


@lru_cache(maxsize=1)
def default_overlay_seed() -> dict[str, object]:
    if not _DEFAULT_INPUT_TEMPLATE_PATH.exists():
        return {}
    try:
        payload = json.loads(_DEFAULT_INPUT_TEMPLATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    simulation_settings = payload.get("simulation_settings")
    tariffs = payload.get("tariffs")
    settings = dict(simulation_settings) if isinstance(simulation_settings, dict) else {}
    tariff_payload = dict(tariffs) if isinstance(tariffs, dict) else {}

    tou_pricing: list[TimeOfUseBand] = []
    base_date = None
    for item in tariff_payload.get("tou_price_yen_per_kWh") or []:
        if not isinstance(item, dict):
            continue
        start_dt = _parse_local_datetime(item.get("start_time"))
        end_dt = _parse_local_datetime(item.get("end_time"))
        if start_dt is None or end_dt is None:
            continue
        if base_date is None:
            base_date = start_dt.date()
        start_minutes = (
            ((start_dt.date() - base_date).days * 24 * 60)
            + (start_dt.hour * 60)
            + start_dt.minute
        )
        end_minutes = (
            ((end_dt.date() - base_date).days * 24 * 60)
            + (end_dt.hour * 60)
            + end_dt.minute
        )
        if start_minutes % 60 != 0 or end_minutes % 60 != 0:
            raise ValueError(
                "Default TOU template must use whole clock-hour boundaries"
            )
        start_hour = int(start_minutes // 60)
        end_hour = int(end_minutes // 60)
        tou_pricing.append(
            TimeOfUseBand(
                start_hour=start_hour,
                end_hour=end_hour,
                price_per_kwh=float(item.get("price_yen_per_kWh") or 0.0),
            )
        )

    default_buy_price = tou_pricing[0].price_per_kwh if tou_pricing else 0.0
    depot_limit = settings.get("charger_site_limit_kW")
    if depot_limit in (None, ""):
        depot_limit = settings.get("contract_power_limit_kW")

    return {
        "charging_constraints": {
            "max_simultaneous_sessions": int(settings.get("num_chargers") or 4),
            "depot_power_limit_kw": (
                float(depot_limit) if depot_limit not in (None, "") else None
            ),
        },
        "cost_coefficients": {
            "tou_pricing": tou_pricing,
            "grid_flat_price_per_kwh": float(default_buy_price),
            "grid_sell_price_per_kwh": 0.0,
            "demand_charge_cost_per_kw": float(
                tariff_payload.get("demand_charge_yen_per_kW_month") or 0.0
            ),
            "diesel_price_per_l": float(tariff_payload.get("diesel_price_yen_per_L") or 0.0),
            "grid_co2_kg_per_kwh": 0.0,
            "co2_price_per_kg": 1.0,
        },
    }


def default_scenario_overlay(
    *,
    scenario_id: str,
    dataset_id: str,
    dataset_version: str,
    random_seed: int = 42,
    depot_ids: Optional[list[str]] = None,
    route_ids: Optional[list[str]] = None,
) -> ScenarioOverlay:
    defaults = default_overlay_seed()
    return ScenarioOverlay(
        scenario_id=scenario_id,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        random_seed=random_seed,
        depot_ids=list(depot_ids or []),
        route_ids=list(route_ids or []),
        charging_constraints=ChargingConfig(**dict(defaults.get("charging_constraints") or {})),
        cost_coefficients=CostConfig(**dict(defaults.get("cost_coefficients") or {})),
    )
