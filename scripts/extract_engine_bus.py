#!/usr/bin/env python3
"""
scripts/extract_engine_bus.py

CLI runner for Phase 1 engine bus extraction.

Usage:
    python scripts/extract_engine_bus.py
    python scripts/extract_engine_bus.py --constant-dir path/to/excel --output-dir path/to/out

Outputs (in data/engine_bus/output/ by default):
    engine_bus_raw.json
    engine_bus_normalized.json
    engine_bus_simulation_library.json
    engine_bus_summary.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is on the path regardless of working directory
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from src.engine_bus_extractor import run_extraction  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract JH25-mode diesel bus performance data from Excel files."
    )
    parser.add_argument(
        "--constant-dir",
        type=Path,
        default=None,
        help="Directory containing the source Excel files (default: <project_root>/constant)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write output files (default: <project_root>/data/engine_bus/output)",
    )
    args = parser.parse_args()

    result = run_extraction(
        constant_dir=args.constant_dir,
        output_dir=args.output_dir,
    )

    # Print a brief summary to stdout
    raw = result["raw"]
    norm = result["normalized"]
    lib = result["simulation_library"]

    print("\n=== Extraction Summary ===")
    print(f"  Raw records:          {len(raw)}")
    print(f"  Normalized records:   {len(norm)}")
    print(f"  Simulation library:   {len(lib)} entries")

    # Per-manufacturer breakdown
    mfrs: dict[str, int] = {}
    for r in norm:
        mfrs[r["manufacturer"]] = mfrs.get(r["manufacturer"], 0) + 1
    for mfr, count in sorted(mfrs.items()):
        print(f"    {mfr}: {count} records")

    # Category breakdown
    cats: dict[str, int] = {}
    for r in norm:
        cats[r["bus_category"]] = cats.get(r["bus_category"], 0) + 1
    print("  Bus categories:")
    for cat, count in sorted(cats.items()):
        print(f"    {cat}: {count}")

    # Quality flags
    flagged = sum(1 for r in norm if r.get("needs_manual_review"))
    print(f"  Records flagged for review: {flagged}")

    print("\nDone.")


if __name__ == "__main__":
    main()
