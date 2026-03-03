"""
engine_bus_loader.py

Loads the engine bus simulation library JSON and maps entries to VehicleSpec
instances that are directly usable by RouteSimulator.

Public API
----------
load_engine_bus_library(path) -> list[VehicleSpec]
    Read engine_bus_simulation_library.json and return one VehicleSpec per entry.

build_mixed_fleet_config(
    engine_bus_ids, ev_specs, trips, tariff, *, diesel_price, label, ...
) -> SimConfig
    Assemble a SimConfig from selected engine-bus IDs (looked up in the library)
    and a caller-supplied list of EV VehicleSpec instances.

Constants for default cost assumptions
---------------------------------------
DEFAULT_PURCHASE_COST_YEN      per bus_category
DEFAULT_LIFETIME_YEAR
DEFAULT_OPERATION_DAYS_PER_YEAR
DEFAULT_FUEL_TANK_CAPACITY_L   per bus_category
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from src.route_cost_simulator import SimConfig, TariffSpec, TripSpec, VehicleSpec

# ---------------------------------------------------------------------------
# Default values for fields absent from the library JSON
# ---------------------------------------------------------------------------

# Purchase cost assumptions (JPY) per bus category
_DEFAULT_PURCHASE_COST_YEN: dict[str, float] = {
    "coach_bus": 25_000_000.0,
    "route_bus": 20_000_000.0,
}
_FALLBACK_PURCHASE_COST_YEN = 22_000_000.0

# Fuel tank capacity (L) per bus category
_DEFAULT_FUEL_TANK_CAPACITY_L: dict[str, float] = {
    "coach_bus": 200.0,
    "route_bus": 150.0,
}
_FALLBACK_FUEL_TANK_CAPACITY_L = 200.0

DEFAULT_LIFETIME_YEAR: float = 12.0
DEFAULT_OPERATION_DAYS_PER_YEAR: float = 300.0
DEFAULT_RESIDUAL_VALUE_YEN: float = 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _entry_to_vehicle_spec(entry: dict) -> VehicleSpec:
    """Convert a single JSON library entry → VehicleSpec."""
    bus_cat: str = entry.get("bus_category", "route_bus")

    purchase_cost = _DEFAULT_PURCHASE_COST_YEN.get(bus_cat, _FALLBACK_PURCHASE_COST_YEN)
    fuel_tank = _DEFAULT_FUEL_TANK_CAPACITY_L.get(
        bus_cat, _FALLBACK_FUEL_TANK_CAPACITY_L
    )

    return VehicleSpec(
        vehicle_id=entry["vehicle_id"],
        vehicle_type="engine_bus",
        passenger_capacity=int(entry.get("passenger_capacity", 70)),
        fuel_economy_km_per_L=float(entry.get("fuel_economy_km_per_L", 0.0)),
        diesel_consumption_L_per_km=float(
            entry.get("diesel_consumption_L_per_km", 0.0)
        ),
        fuel_tank_capacity_L=fuel_tank,
        purchase_cost_yen=purchase_cost,
        residual_value_yen=DEFAULT_RESIDUAL_VALUE_YEN,
        lifetime_year=DEFAULT_LIFETIME_YEAR,
        operation_days_per_year=DEFAULT_OPERATION_DAYS_PER_YEAR,
        # Store extra metadata as route_compatibility comment not applicable;
        # depot stays default "depot_01"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DEFAULT_LIBRARY_PATH = (
    Path(__file__).parent.parent
    / "data"
    / "engine_bus"
    / "output"
    / "engine_bus_simulation_library.json"
)


def load_engine_bus_library(
    path: str | Path | None = None,
) -> list[VehicleSpec]:
    """
    Load the engine bus simulation library JSON and return a list of VehicleSpec.

    Parameters
    ----------
    path : str | Path | None
        Path to the JSON file.  Defaults to
        ``data/engine_bus/output/engine_bus_simulation_library.json``
        (relative to project root).

    Returns
    -------
    list[VehicleSpec]
        One VehicleSpec per library entry, vehicle_type="engine_bus".
    """
    resolved = Path(path) if path is not None else _DEFAULT_LIBRARY_PATH
    raw: list[dict] = json.loads(resolved.read_text(encoding="utf-8"))
    return [_entry_to_vehicle_spec(entry) for entry in raw]


def get_engine_bus_by_id(
    vehicle_id: str,
    path: str | Path | None = None,
) -> VehicleSpec:
    """
    Return a single VehicleSpec for the given vehicle_id.

    Raises
    ------
    KeyError
        If vehicle_id is not found in the library.
    """
    library = load_engine_bus_library(path)
    lut = {v.vehicle_id: v for v in library}
    if vehicle_id not in lut:
        raise KeyError(
            f"vehicle_id '{vehicle_id}' not found in engine bus library. "
            f"Available IDs: {sorted(lut.keys())}"
        )
    return lut[vehicle_id]


def build_mixed_fleet_config(
    engine_bus_ids: Sequence[str],
    ev_specs: Sequence[VehicleSpec],
    trips: Sequence[TripSpec],
    tariff: TariffSpec | None = None,
    *,
    diesel_price_yen_per_L: float = 150.0,
    label: str = "mixed_fleet",
    delta_t_min: int = 30,
    time_horizon_hours: float = 24.0,
    charger_site_limit_kW: float = 1e9,
    num_chargers: int = 999,
    library_path: str | Path | None = None,
) -> SimConfig:
    """
    Build a SimConfig combining selected engine buses and EV specs.

    Parameters
    ----------
    engine_bus_ids : sequence of str
        vehicle_id values to pull from the library.
    ev_specs : sequence of VehicleSpec
        Pre-constructed EV VehicleSpec instances (vehicle_type="ev_bus").
    trips : sequence of TripSpec
        Route profile trips.
    tariff : TariffSpec | None
        Electricity tariff.  Defaults to a flat 25 yen/kWh tariff.
    diesel_price_yen_per_L : float
        Diesel price used in fuel cost calculation.
    label : str
        Human-readable label for this simulation run.
    delta_t_min : int
        Time-slot resolution in minutes (default 30).
    time_horizon_hours : float
        Simulation horizon in hours (default 24).
    charger_site_limit_kW : float
        Maximum total site charging power.
    num_chargers : int
        Maximum simultaneous EV chargers.
    library_path : str | Path | None
        Override path to the library JSON.

    Returns
    -------
    SimConfig
    """
    library = load_engine_bus_library(library_path)
    lut = {v.vehicle_id: v for v in library}

    missing = [vid for vid in engine_bus_ids if vid not in lut]
    if missing:
        raise KeyError(
            f"The following vehicle_id(s) were not found in the engine bus library: "
            f"{missing}"
        )

    engine_specs = [lut[vid] for vid in engine_bus_ids]
    fleet: list[VehicleSpec] = list(ev_specs) + engine_specs

    cfg = SimConfig()
    cfg.fleet = fleet
    cfg.trips = list(trips)
    cfg.tariff = tariff if tariff is not None else TariffSpec()
    cfg.diesel_price_yen_per_L = diesel_price_yen_per_L
    cfg.label = label
    cfg.delta_t_min = delta_t_min
    cfg.time_horizon_hours = time_horizon_hours
    cfg.charger_site_limit_kW = charger_site_limit_kW
    cfg.num_chargers = num_chargers
    return cfg
