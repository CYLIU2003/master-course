"""
scripts/batch_sensitivity.py

Parameter sweep for mixed-fleet EV/engine-bus cost & CO2 sensitivity analysis.

Sweeps:
  ev_count              : 0, 1, 2, 3
  diesel_price_yen_per_L: 130, 150, 170
  flat_tou_yen_per_kWh  : 20, 25, 30
  daily_distance_km     : 100, 200

Output: results/sensitivity/batch_results.csv
Columns:
  scenario_id, ev_count, diesel_price, tou_price, daily_distance_km,
  total_cost_yen, fuel_cost_yen, electricity_cost_yen, demand_charge_yen,
  total_fuel_L, peak_grid_kW, co2_kg

CO2 formula:
  total_fuel_L * 2.58 + total_grid_kWh * 0.44

Usage:
  python scripts/batch_sensitivity.py
  python scripts/batch_sensitivity.py --output results/sensitivity/batch_results.csv
"""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
from pathlib import Path

# Make sure project root is importable when run as a script
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.engine_bus_loader import load_engine_bus_library
from src.route_cost_simulator import (
    RouteSimulator,
    SimConfig,
    TariffSpec,
    TripSpec,
    VehicleSpec,
)

# ---------------------------------------------------------------------------
# Sweep ranges
# ---------------------------------------------------------------------------

EV_COUNTS = [0, 1, 2, 3]
DIESEL_PRICES = [130.0, 150.0, 170.0]
TOU_PRICES = [20.0, 25.0, 30.0]
DAILY_DISTANCES = [100.0, 200.0]

# ---------------------------------------------------------------------------
# Representative engine bus: use the first "representative" route_bus entry
# ---------------------------------------------------------------------------

_ENGINE_BUS_ID = "hino_2sg_hl2anbp_04"  # route_bus, representative, 5.38 km/L

# EV prototype
_EV_BATTERY_kWh = 300.0
_EV_USABLE_kWh = 270.0
_EV_CONSUMPTION_kWh_per_km = 1.2
_EV_CHARGING_kW = 90.0
_EV_PURCHASE_YEN = 50_000_000
_EV_LIFETIME_YR = 12.0
_EV_OP_DAYS = 300.0

CO2_DIESEL_kg_per_L = 2.58
CO2_GRID_kg_per_kWh = 0.44

OUTPUT_DEFAULT = Path("results/sensitivity/batch_results.csv")

CSV_COLUMNS = [
    "scenario_id",
    "ev_count",
    "diesel_price",
    "tou_price",
    "daily_distance_km",
    "total_cost_yen",
    "fuel_cost_yen",
    "electricity_cost_yen",
    "demand_charge_yen",
    "total_fuel_L",
    "peak_grid_kW",
    "co2_kg",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ev_spec(idx: int) -> VehicleSpec:
    return VehicleSpec(
        vehicle_id=f"ev_{idx:02d}",
        vehicle_type="ev_bus",
        passenger_capacity=60,
        battery_capacity_kWh=_EV_BATTERY_kWh,
        usable_battery_capacity_kWh=_EV_USABLE_kWh,
        initial_soc=1.0,
        min_soc=0.15,
        max_soc=1.0,
        energy_consumption_kWh_per_km_base=_EV_CONSUMPTION_kWh_per_km,
        charging_power_max_kW=_EV_CHARGING_kW,
        charging_efficiency=0.95,
        purchase_cost_yen=_EV_PURCHASE_YEN,
        residual_value_yen=0.0,
        lifetime_year=_EV_LIFETIME_YR,
        operation_days_per_year=_EV_OP_DAYS,
    )


def _make_trips(daily_distance_km: float) -> list[TripSpec]:
    """Generate a simple two-trip route profile that covers daily_distance_km."""
    half = daily_distance_km / 2.0
    return [
        TripSpec(
            trip_id="t_am",
            route_id="R1",
            start_time="08:00",
            end_time="11:00",
            distance_km=half,
        ),
        TripSpec(
            trip_id="t_pm",
            route_id="R1",
            start_time="14:00",
            end_time="17:00",
            distance_km=half,
        ),
    ]


def _build_config(
    ev_count: int,
    diesel_price: float,
    tou_price: float,
    daily_distance_km: float,
    engine_spec: VehicleSpec,
    label: str,
) -> SimConfig:
    ev_fleet = [_make_ev_spec(i) for i in range(ev_count)]
    # Always include one engine bus as fallback (even when ev_count > 0)
    fleet = ev_fleet + [engine_spec]

    tariff = TariffSpec(flat_price_yen_per_kWh=tou_price)
    trips = _make_trips(daily_distance_km)

    cfg = SimConfig()
    cfg.fleet = fleet
    cfg.trips = trips
    cfg.tariff = tariff
    cfg.diesel_price_yen_per_L = diesel_price
    cfg.delta_t_min = 30
    cfg.time_horizon_hours = 24.0
    cfg.label = label
    cfg.charger_site_limit_kW = ev_count * _EV_CHARGING_kW + 10.0 if ev_count else 10.0
    cfg.num_chargers = max(ev_count, 1)
    return cfg


def run_sweep(output_path: Path = OUTPUT_DEFAULT) -> list[dict]:
    """Run the full parameter sweep and return rows (also writes CSV)."""
    # Load engine bus spec from library
    library = load_engine_bus_library()
    lut = {v.vehicle_id: v for v in library}
    if _ENGINE_BUS_ID not in lut:
        # Fall back to first available
        engine_spec = library[0]
        print(
            f"[warn] {_ENGINE_BUS_ID} not found in library; "
            f"using {engine_spec.vehicle_id}"
        )
    else:
        engine_spec = lut[_ENGINE_BUS_ID]

    rows: list[dict] = []
    scenario_id = 0

    combos = list(
        itertools.product(EV_COUNTS, DIESEL_PRICES, TOU_PRICES, DAILY_DISTANCES)
    )
    total = len(combos)
    print(f"[batch_sensitivity] Running {total} scenarios …")

    for ev_count, diesel_price, tou_price, daily_dist in combos:
        scenario_id += 1
        label = (
            f"s{scenario_id:03d}_ev{ev_count}"
            f"_d{int(diesel_price)}_t{int(tou_price)}_km{int(daily_dist)}"
        )

        cfg = _build_config(
            ev_count=ev_count,
            diesel_price=diesel_price,
            tou_price=tou_price,
            daily_distance_km=daily_dist,
            engine_spec=engine_spec,
            label=label,
        )

        try:
            sim = RouteSimulator(cfg)
            cb = sim.cost_breakdown()

            total_fuel_L = cb["total_fuel_consumption_L"]
            total_grid_kWh = cb["total_grid_purchase_kWh"]
            co2_kg = (
                total_fuel_L * CO2_DIESEL_kg_per_L
                + total_grid_kWh * CO2_GRID_kg_per_kWh
            )

            rows.append(
                {
                    "scenario_id": label,
                    "ev_count": ev_count,
                    "diesel_price": diesel_price,
                    "tou_price": tou_price,
                    "daily_distance_km": daily_dist,
                    "total_cost_yen": cb["total_cost_yen"],
                    "fuel_cost_yen": cb["fuel_cost_yen"],
                    "electricity_cost_yen": cb["electricity_cost_yen"],
                    "demand_charge_yen": cb["demand_charge_yen"],
                    "total_fuel_L": total_fuel_L,
                    "peak_grid_kW": cb["peak_demand_kW"],
                    "co2_kg": round(co2_kg, 3),
                }
            )
        except Exception as exc:
            print(f"  [warn] scenario {label} failed: {exc}")
            rows.append(
                {
                    "scenario_id": label,
                    "ev_count": ev_count,
                    "diesel_price": diesel_price,
                    "tou_price": tou_price,
                    "daily_distance_km": daily_dist,
                    "total_cost_yen": None,
                    "fuel_cost_yen": None,
                    "electricity_cost_yen": None,
                    "demand_charge_yen": None,
                    "total_fuel_L": None,
                    "peak_grid_kW": None,
                    "co2_kg": None,
                }
            )

    # Write CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[batch_sensitivity] Done. {len(rows)} rows → {output_path}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch parameter sensitivity sweep for EV/engine-bus fleet."
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_DEFAULT),
        help=f"Output CSV path (default: {OUTPUT_DEFAULT})",
    )
    args = parser.parse_args()
    run_sweep(Path(args.output))


if __name__ == "__main__":
    main()
