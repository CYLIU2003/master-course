from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from src.reporting import rebuild_reporting_artifacts_in_place


RUN_EXPECTATIONS = {
    "run_20260606_1559": {
        "grid_purchase_cost_jpy": 88294.09555407467,
        "demand_charge_cost_jpy": 23717.27170526316,
        "fuel_cost_jpy": 63839.75993013598,
        "reported_total_cost_jpy": 179339.67070980853,
        "gross_operating_cost_jpy": 179339.67070980853,
        "objective_value_jpy": 68714.63958525108,
        "bess_capacity_kwh": 600.0,
        "bess_soc_min_kwh": 120.0,
        "bess_soc_max_kwh": 480.0,
    },
    "run_20260606_1624": {
        "grid_purchase_cost_jpy": 94909.54756549544,
        "demand_charge_cost_jpy": 25834.636706672536,
        "fuel_cost_jpy": 64416.12588291561,
        "reported_total_cost_jpy": 188812.89243830735,
        "gross_operating_cost_jpy": 188812.89243830735,
        "objective_value_jpy": 67435.50521983395,
        "bess_capacity_kwh": 600.0,
        "bess_soc_min_kwh": 120.0,
        "bess_soc_max_kwh": 480.0,
    },
}


def source_run_dir(run_id: str) -> Path:
    path = Path("output") / "2026-06-06" / run_id
    if not path.exists():
        pytest.skip(f"regression run data not found: {path}")
    return path


def finalized_run(tmp_path: Path, run_id: str) -> Path:
    output = tmp_path / run_id
    shutil.copytree(source_run_dir(run_id), output)
    rebuild_reporting_artifacts_in_place(output)
    return output


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def key_values(path: Path) -> dict[str, float]:
    rows = read_rows(path)
    values: dict[str, float] = {}
    for row in rows:
        key = row.get("key") or row.get("term") or row.get("component")
        value = row.get("value") or row.get("yen")
        if key and value not in (None, ""):
            try:
                values[key] = float(value)
            except ValueError:
                continue
    return values


def sum_column(path: Path, column: str) -> float:
    return sum(float(row.get(column) or 0.0) for row in read_rows(path))
