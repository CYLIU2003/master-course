"""
run_route_cost_sim.py

CLI runner for the route-cost simulator (src/route_cost_simulator.py).

Usage:
    # Run from a JSON config file:
    python scripts/run_route_cost_sim.py --config path/to/sim_config.json

    # Write outputs to a specific directory:
    python scripts/run_route_cost_sim.py --config path/to/sim_config.json --output-dir results/my_run

    # Use the built-in demo scenario (2 EVs + 1 engine bus):
    python scripts/run_route_cost_sim.py --demo

    # Demo with custom output dir:
    python scripts/run_route_cost_sim.py --demo --output-dir results/demo_run

Config file format (JSON):
{
  "label": "my_scenario",
  "delta_t_min": 30,
  "time_horizon_hours": 24,
  "diesel_price_yen_per_L": 150,
  "fleet": [
    {
      "vehicle_id": "ev_01",
      "vehicle_type": "ev_bus",
      "battery_capacity_kWh": 200,
      "usable_battery_capacity_kWh": 180,
      "initial_soc": 0.9,
      "min_soc": 0.15,
      "max_soc": 1.0,
      "energy_consumption_kWh_per_km_base": 1.2,
      "charging_power_max_kW": 60,
      "charging_efficiency": 0.95,
      "passenger_capacity": 70,
      "purchase_cost_yen": 50000000,
      "lifetime_year": 12,
      "operation_days_per_year": 300
    },
    {
      "vehicle_id": "eng_01",
      "vehicle_type": "engine_bus",
      "fuel_economy_km_per_L": 5.38,
      "passenger_capacity": 79,
      "purchase_cost_yen": 25000000,
      "lifetime_year": 12,
      "operation_days_per_year": 300
    }
  ],
  "route_profile": [
    {
      "trip_id": "T001",
      "route_id": "R01",
      "start_time": "07:00",
      "end_time": "08:00",
      "distance_km": 20,
      "deadhead_distance_before_km": 2
    }
  ],
  "tariff": {
    "flat_price_yen_per_kWh": 25,
    "demand_charge_yen_per_kW_month": 1500,
    "cost_time_basis": "daily"
  }
}
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from src.route_cost_simulator import RouteSimulator, SimConfig


# ---------------------------------------------------------------------------
# Demo scenario: 2 EVs + 1 Hino representative engine bus, 8 trips
# ---------------------------------------------------------------------------

_DEMO_CONFIG: dict = {
    "label": "demo_2ev_1eng",
    "delta_t_min": 30,
    "time_horizon_hours": 24.0,
    "diesel_price_yen_per_L": 150.0,
    "fleet": [
        {
            "vehicle_id": "ev_01",
            "vehicle_type": "ev_bus",
            "battery_capacity_kWh": 200.0,
            "usable_battery_capacity_kWh": 180.0,
            "initial_soc": 0.90,
            "min_soc": 0.15,
            "max_soc": 1.0,
            "energy_consumption_kWh_per_km_base": 1.2,
            "charging_power_max_kW": 60.0,
            "charging_efficiency": 0.95,
            "passenger_capacity": 70,
            "purchase_cost_yen": 50_000_000,
            "residual_value_yen": 5_000_000,
            "lifetime_year": 12,
            "operation_days_per_year": 300,
        },
        {
            "vehicle_id": "ev_02",
            "vehicle_type": "ev_bus",
            "battery_capacity_kWh": 200.0,
            "usable_battery_capacity_kWh": 180.0,
            "initial_soc": 0.90,
            "min_soc": 0.15,
            "max_soc": 1.0,
            "energy_consumption_kWh_per_km_base": 1.2,
            "charging_power_max_kW": 60.0,
            "charging_efficiency": 0.95,
            "passenger_capacity": 70,
            "purchase_cost_yen": 50_000_000,
            "residual_value_yen": 5_000_000,
            "lifetime_year": 12,
            "operation_days_per_year": 300,
        },
        {
            # Hino representative route_bus from Phase 2 library
            "vehicle_id": "eng_hino_rep",
            "vehicle_type": "engine_bus",
            "fuel_economy_km_per_L": 5.38,
            "diesel_consumption_L_per_km": 0.1859,
            "fuel_tank_capacity_L": 200.0,
            "passenger_capacity": 79,
            "purchase_cost_yen": 25_000_000,
            "residual_value_yen": 2_000_000,
            "lifetime_year": 12,
            "operation_days_per_year": 300,
        },
    ],
    "route_profile": [
        # Morning peak
        {
            "trip_id": "T001",
            "route_id": "R01",
            "start_time": "06:00",
            "end_time": "07:30",
            "distance_km": 22.0,
            "deadhead_distance_before_km": 2.0,
            "deadhead_distance_after_km": 1.0,
        },
        {
            "trip_id": "T002",
            "route_id": "R01",
            "start_time": "06:15",
            "end_time": "07:45",
            "distance_km": 22.0,
            "deadhead_distance_before_km": 2.0,
            "deadhead_distance_after_km": 1.0,
        },
        {
            "trip_id": "T003",
            "route_id": "R02",
            "start_time": "07:30",
            "end_time": "08:30",
            "distance_km": 18.0,
            "deadhead_distance_before_km": 1.5,
        },
        # Midday
        {
            "trip_id": "T004",
            "route_id": "R01",
            "start_time": "10:00",
            "end_time": "11:30",
            "distance_km": 22.0,
        },
        {
            "trip_id": "T005",
            "route_id": "R02",
            "start_time": "11:00",
            "end_time": "12:00",
            "distance_km": 18.0,
        },
        # Afternoon peak
        {
            "trip_id": "T006",
            "route_id": "R01",
            "start_time": "16:30",
            "end_time": "18:00",
            "distance_km": 22.0,
            "deadhead_distance_after_km": 2.0,
        },
        {
            "trip_id": "T007",
            "route_id": "R01",
            "start_time": "17:00",
            "end_time": "18:30",
            "distance_km": 22.0,
            "deadhead_distance_after_km": 2.0,
        },
        {
            "trip_id": "T008",
            "route_id": "R02",
            "start_time": "17:30",
            "end_time": "18:30",
            "distance_km": 18.0,
        },
    ],
    "tariff": {
        "flat_price_yen_per_kWh": 25.0,
        "tou_price_yen_per_kWh": {
            # slots 0-12 = 00:00-06:00 (off-peak): 18 yen
            **{str(i): 18.0 for i in range(12)},
            # slots 12-22 = 06:00-11:00 (shoulder): 25 yen
            **{str(i): 25.0 for i in range(12, 22)},
            # slots 22-36 = 11:00-18:00 (off-peak): 18 yen
            **{str(i): 18.0 for i in range(22, 36)},
            # slots 36-44 = 18:00-22:00 (peak): 35 yen
            **{str(i): 35.0 for i in range(36, 44)},
            # slots 44-48 = 22:00-24:00 (off-peak): 18 yen
            **{str(i): 18.0 for i in range(44, 48)},
        },
        "demand_charge_yen_per_kW_month": 1500.0,
        "contract_power_limit_kW": 200.0,
        "contract_penalty_mode": "penalty",
        "contract_penalty_yen_per_kW": 3000.0,
        "cost_time_basis": "daily",
    },
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run the route-cost simulator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--config", type=Path, help="Path to JSON simulation config file.")
    grp.add_argument(
        "--demo",
        action="store_true",
        help="Run the built-in demo scenario (2 EVs + 1 Hino engine bus, 8 trips).",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for output files. Default: results/route_cost/<label>",
    )
    p.add_argument(
        "--print-summary",
        action="store_true",
        default=True,
        help="Print cost summary to stdout (default: true).",
    )
    p.add_argument(
        "--no-print",
        action="store_true",
        help="Suppress stdout summary.",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()

    # Load config
    if args.demo:
        cfg = SimConfig.from_dict(_DEMO_CONFIG)
        print("[INFO] Running built-in demo scenario: demo_2ev_1eng")
    else:
        cfg = SimConfig.from_json(args.config)
        print(f"[INFO] Loaded config: {args.config}  label={cfg.label}")

    # Determine output dir
    if args.output_dir is not None:
        out_dir = args.output_dir
    else:
        root = Path(__file__).resolve().parent.parent
        out_dir = root / "results" / "route_cost" / cfg.label

    print(f"[INFO] Output dir: {out_dir}")

    # Run simulation
    t0 = time.perf_counter()
    sim = RouteSimulator(cfg)
    result = sim.run()
    elapsed = time.perf_counter() - t0

    # Save outputs
    paths = result.save(out_dir)

    # Print summary
    if not args.no_print:
        cb = result.cost_breakdown()
        print("\n" + "=" * 60)
        print(f"  Simulation: {cb['label']}")
        print("=" * 60)
        print(f"  Trips total:       {len(cfg.trips)}")
        print(f"  Unassigned trips:  {cb['unassigned_trips']}")
        print(f"  Peak grid demand:  {cb['peak_demand_kW']:.1f} kW")
        print(f"  Total grid kWh:    {cb['total_grid_purchase_kWh']:.1f} kWh")
        print(f"  Total fuel:        {cb['total_fuel_consumption_L']:.1f} L")
        print("-" * 60)
        yen = "JPY"
        print(f"  Vehicle capex:     {yen} {cb['vehicle_capex_cost_yen']:>12,.0f}")
        print(f"  Electricity cost:  {yen} {cb['electricity_cost_yen']:>12,.0f}")
        print(f"  Demand charge:     {yen} {cb['demand_charge_yen']:>12,.0f}")
        print(f"  Fuel cost:         {yen} {cb['fuel_cost_yen']:>12,.0f}")
        print(f"  Contract excess:   {yen} {cb['contract_excess_cost_yen']:>12,.0f}")
        print(f"  {'TOTAL COST':17s}  {yen} {cb['total_cost_yen']:>12,.0f}")
        print("-" * 60)
        print(f"  Solve time:        {elapsed:.3f} s")
        print("=" * 60)
        print(f"\nOutputs written to: {out_dir}")
        for name, p in paths.items():
            print(f"  {name:<22}: {p.name}")

    # Write a demo JSON config next to results for reference
    if args.demo:
        demo_cfg_path = out_dir / "demo_config.json"
        demo_cfg_path.write_text(
            json.dumps(_DEMO_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[INFO] Demo config written to: {demo_cfg_path}")


if __name__ == "__main__":
    main()
