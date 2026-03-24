from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build depot energy asset JSON for PV/BESS scenario cases")
    parser.add_argument("--depot-id", required=True)
    parser.add_argument("--pv-case-id", default="none")
    parser.add_argument("--pv-capacity-kw", type=float, default=0.0)
    parser.add_argument("--bess-energy-kwh", type=float, default=0.0)
    parser.add_argument("--bess-power-kw", type=float, default=0.0)
    parser.add_argument("--allow-grid-to-bess", action="store_true")
    parser.add_argument("--provisional-energy-cost-yen-per-kwh", type=float, default=0.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    bess_enabled = args.bess_energy_kwh > 0.0 and args.bess_power_kw > 0.0
    payload = {
        "depot_id": args.depot_id,
        "pv_enabled": args.pv_capacity_kw > 0.0,
        "pv_case_id": args.pv_case_id,
        "pv_capacity_kw": float(args.pv_capacity_kw),
        "bess_enabled": bool(bess_enabled),
        "bess_energy_kwh": float(args.bess_energy_kwh),
        "bess_power_kw": float(args.bess_power_kw),
        "bess_initial_soc_kwh": float(args.bess_energy_kwh) * 0.5 if bess_enabled else 0.0,
        "bess_soc_min_kwh": float(args.bess_energy_kwh) * 0.1 if bess_enabled else 0.0,
        "bess_soc_max_kwh": float(args.bess_energy_kwh) if bess_enabled else 0.0,
        "allow_grid_to_bess": bool(args.allow_grid_to_bess),
        "grid_to_bess_price_mode": "tou",
        "bess_priority_mode": "cost_driven",
        "provisional_energy_cost_yen_per_kwh": float(args.provisional_energy_cost_yen_per_kwh),
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
