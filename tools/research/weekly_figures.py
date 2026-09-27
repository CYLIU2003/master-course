"""Render saved, verified weekly numbers without preparing or solving again."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from tools.research.weekly_results import render_week, write_json

NUMERICAL_FILES = ("weekly_summary.json", "energy_15min.csv", "vehicle_soc.csv",
                   "vehicle_schedule.csv", "charging_schedule.csv", "daily_summary.csv")


def hashes(directory: Path) -> dict[str, str]:
    return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in NUMERICAL_FILES}


def render_verified_week(output: Path, row: dict, times: list[dict], soc: list[dict],
                         evidence: dict[str, str]) -> dict:
    """Only rendering is recoverable here; numerical validation happens upstream."""
    receipt = {"schema_version": "weekly_figures_v1", "numerical_status": "VERIFIED",
               "numerical_sha256": evidence, "figure_status": "RUNNING", "solver_restarted": False}
    write_json(output / "figure_status.json", receipt)
    try:
        render_week(output, row, times, soc)
        receipt.update(figure_status="COMPLETED", figure_sha256=hashlib.sha256(
            (output / "weekly_energy_soc.png").read_bytes()).hexdigest())
    except Exception as exc:
        # Plotting/library failures must not invalidate already checked accounting.
        # Persist the failure and retry only figures; never suppress validation errors.
        receipt.update(figure_status="FAILED", error_type=type(exc).__name__, error=str(exc))
    write_json(output / "figure_status.json", receipt)
    return receipt


def retry_figures(source: Path, output: Path) -> dict:
    receipt = json.loads((source / "figure_status.json").read_text(encoding="utf-8"))
    if receipt.get("numerical_status") != "VERIFIED" or receipt.get("numerical_sha256") != hashes(source):
        raise ValueError("Verified numerical files changed or evidence is missing")
    row = json.loads((source / "weekly_summary.json").read_text(encoding="utf-8"))
    if row.get("evaluation_status") != "VERIFIED_CONDITIONAL_WEEKLY_EVALUATION":
        raise ValueError("Verified weekly export is required")
    def series(name: str) -> list[dict]:
        with (source / name).open(encoding="utf-8-sig", newline="") as stream:
            return [{key: value if key in {"vehicle_id", "interval_start_jst", "period", "week"} else float(value)
                     for key, value in item.items()} for item in csv.DictReader(stream)]
    times, soc = series("energy_15min.csv"), series("vehicle_soc.csv")
    output.mkdir(parents=True, exist_ok=False)
    result = render_verified_week(output, row, times, soc, receipt["numerical_sha256"])
    result["source_results"] = str(source.resolve())
    write_json(output / "figure_status.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = retry_figures(args.results, args.output)
    print(json.dumps(result, ensure_ascii=False))
    if result["figure_status"] != "COMPLETED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
