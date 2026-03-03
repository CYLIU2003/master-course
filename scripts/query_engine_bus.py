"""
query_engine_bus.py

CLI for Phase 2 engine bus vehicle selector.

Usage examples:
    # Representative Hino route_bus
    python scripts/query_engine_bus.py --manufacturer hino --category route_bus --mode representative

    # Conservative any route_bus with capacity >= 70
    python scripts/query_engine_bus.py --category route_bus --capacity-min 70 --mode conservative

    # Exact match: route_bus, Isuzu, capacity 75-85, GVW 13000-16000
    python scripts/query_engine_bus.py --manufacturer isuzu --category route_bus \\
        --capacity-min 75 --capacity-max 85 --gvw-min 13000 --gvw-max 16000 --mode exact_match

    # Look up by model_code
    python scripts/query_engine_bus.py --model-code LV290N3

    # Return top 3 best-efficiency coach buses
    python scripts/query_engine_bus.py --category coach_bus --mode best_efficiency --top-n 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure src/ is on the path when called from project root
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from src.engine_bus_extractor import run_extraction, select_vehicles


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Query the engine bus database (Phase 2 selector).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--mode",
        choices=["exact_match", "representative", "conservative", "best_efficiency"],
        default="exact_match",
        help="Selection mode (default: exact_match)",
    )
    p.add_argument(
        "--manufacturer",
        default=None,
        help="Manufacturer name substring: hino | isuzu | mitsubishifuso",
    )
    p.add_argument(
        "--category",
        dest="bus_category",
        choices=["route_bus", "coach_bus"],
        default=None,
        help="Bus category",
    )
    p.add_argument(
        "--capacity-min", type=int, default=None, help="Min passenger capacity"
    )
    p.add_argument(
        "--capacity-max", type=int, default=None, help="Max passenger capacity"
    )
    p.add_argument("--gvw-min", type=int, default=None, help="Min GVW (kg)")
    p.add_argument("--gvw-max", type=int, default=None, help="Max GVW (kg)")
    p.add_argument("--power-min", type=float, default=None, help="Min max_power_kW")
    p.add_argument("--power-max", type=float, default=None, help="Max max_power_kW")
    p.add_argument(
        "--model-code", default=None, help="Exact model_code lookup (priority)"
    )
    p.add_argument(
        "--top-n",
        type=int,
        default=1,
        help="Number of results to return (default: 1)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory containing engine_bus_normalized.json (default: auto-detected)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of human-readable summary",
    )
    return p


def _load_normalized(output_dir: Path | None) -> list[dict]:
    """Load normalized records from pre-built JSON, or re-run extraction."""
    if output_dir is None:
        root = Path(__file__).resolve().parent.parent
        output_dir = root / "data" / "engine_bus" / "output"

    norm_file = output_dir / "engine_bus_normalized.json"
    if norm_file.exists():
        data = json.loads(norm_file.read_text(encoding="utf-8"))
        return data

    # Fall back to re-running extraction
    print(
        "[INFO] Pre-built normalized data not found; running extraction...",
        file=sys.stderr,
    )
    result = run_extraction()
    return result["normalized"]


def _safe_print(s: str) -> None:
    """Print a string, replacing unencodable characters for the current console."""
    enc = sys.stdout.encoding or "utf-8"
    print(s.encode(enc, errors="replace").decode(enc))


def _print_record(rec: dict, idx: int) -> None:
    """Pretty-print a single record."""
    _safe_print(f"\n--- Result {idx} ---")
    key_fields = [
        ("manufacturer", "Manufacturer"),
        ("model_code", "Model code"),
        ("bus_category", "Category"),
        ("vehicle_name", "Vehicle name"),
        ("passenger_capacity", "Capacity (pax)"),
        ("gross_vehicle_weight_kg", "GVW (kg)"),
        ("vehicle_weight_kg", "Curb weight (kg)"),
        ("max_power_kW", "Max power (kW)"),
        ("max_torque_Nm", "Max torque (N-m)"),
        ("engine_model", "Engine model"),
        ("displacement_L", "Displacement (L)"),
        ("transmission", "Transmission"),
        ("fuel_economy_km_per_L", "Fuel economy (km/L)"),
        ("diesel_consumption_L_per_km", "Diesel consumption (L/km)"),
        ("co2_g_per_km", "CO2 (g/km)"),
        ("co2_g_per_pax_km", "CO2 per pax*km (g)"),
        ("equivalent_energy_kWh_per_km", "Equiv. energy (kWh/km)"),
        ("fuel_standard_km_per_L", "JH25 std (km/L)"),
        ("fuel_standard_achievement_r7_pct", "R7 achievement (%)"),
        ("low_emission_certification", "Low emission cert."),
        ("source_file", "Source file"),
        ("source_row", "Source row"),
    ]
    for fld, label in key_fields:
        v = rec.get(fld)
        if v is not None:
            if isinstance(v, float):
                _safe_print(f"  {label:<35}: {v:.4g}")
            else:
                _safe_print(f"  {label:<35}: {v}")


def main() -> None:
    args = _build_parser().parse_args()

    normalized = _load_normalized(args.output_dir)

    results = select_vehicles(
        normalized,
        mode=args.mode,
        manufacturer=args.manufacturer,
        bus_category=args.bus_category,
        capacity_min=args.capacity_min,
        capacity_max=args.capacity_max,
        gvw_min=args.gvw_min,
        gvw_max=args.gvw_max,
        power_min=args.power_min,
        power_max=args.power_max,
        model_code=args.model_code,
        top_n=args.top_n,
    )

    if not results:
        print(
            "[WARN] No matching vehicles found for the given criteria.", file=sys.stderr
        )
        sys.exit(1)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        return

    print(
        f"\nQuery results: mode={args.mode}, matched={len(results)} record(s) "
        f"from {len(normalized)} total"
    )
    for i, rec in enumerate(results, 1):
        _print_record(rec, i)

    print()


if __name__ == "__main__":
    main()
