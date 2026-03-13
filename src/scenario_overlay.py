from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class TimeOfUseBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_hour: int = Field(ge=0, le=47)
    end_hour: int = Field(ge=1, le=48)
    price_per_kwh: float = Field(ge=0.0)


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


class CostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tou_pricing: list[TimeOfUseBand] = Field(default_factory=list)
    demand_charge_cost_per_kw: float = Field(default=0.0, ge=0.0)
    pv_enabled: bool = False
    pv_scale: float = Field(default=1.0, ge=0.0)
    diesel_price_per_l: float = Field(default=0.0, ge=0.0)


class SolverConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal[
        "milp",
        "alns",
        "hybrid",
        "mode_milp_only",
        "mode_alns_only",
        "mode_alns_milp",
    ] = "hybrid"
    time_limit_seconds: int = Field(default=300, ge=1)
    mip_gap: float = Field(default=0.01, ge=0.0)
    alns_iterations: int = Field(default=500, ge=1)


class ScenarioOverlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    dataset_id: str
    dataset_version: str
    random_seed: int
    depot_ids: list[str] = Field(default_factory=list)
    route_ids: list[str] = Field(default_factory=list)
    fleet: FleetConfig = Field(default_factory=FleetConfig)
    charging_constraints: ChargingConfig = Field(default_factory=ChargingConfig)
    cost_coefficients: CostConfig = Field(default_factory=CostConfig)
    solver_config: SolverConfig = Field(default_factory=SolverConfig)


def default_scenario_overlay(
    *,
    scenario_id: str,
    dataset_id: str,
    dataset_version: str,
    random_seed: int = 42,
    depot_ids: Optional[list[str]] = None,
    route_ids: Optional[list[str]] = None,
) -> ScenarioOverlay:
    return ScenarioOverlay(
        scenario_id=scenario_id,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        random_seed=random_seed,
        depot_ids=list(depot_ids or []),
        route_ids=list(route_ids or []),
    )
