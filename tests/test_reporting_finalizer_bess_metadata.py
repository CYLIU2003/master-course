from __future__ import annotations

import csv
import json

import pytest

from src.reporting.canonical_reporting import update_energy_flow_bess_metadata
from tests._reporting_finalizer_utils import RUN_EXPECTATIONS, finalized_run, read_rows


def _inferred_capacity_from_bess_timeseries(rows):
    capacities = []
    for row in rows:
        soc = float(row.get("bess_soc_kwh") or 0.0)
        percent = float(row.get("bess_soc_percent") or 0.0)
        if soc > 0.0 and percent > 0.0:
            capacities.append(soc * 100.0 / percent)
    return sorted(capacities)[len(capacities) // 2]


@pytest.mark.parametrize("run_id", sorted(RUN_EXPECTATIONS))
def test_reporting_finalizer_bess_metadata(tmp_path, run_id):
    run_dir = finalized_run(tmp_path, run_id)
    expected = RUN_EXPECTATIONS[run_id]
    energy_rows = read_rows(run_dir / "graph" / "energy_flow_ledger.csv")
    bess_rows = read_rows(run_dir / "graph" / "bess_timeseries.csv")

    assert max(float(row["bess_capacity_kwh"]) for row in energy_rows) == pytest.approx(
        _inferred_capacity_from_bess_timeseries(bess_rows)
    )
    assert max(float(row["bess_capacity_kwh"]) for row in energy_rows) == pytest.approx(expected["bess_capacity_kwh"])
    assert max(float(row["bess_soc_min_kwh"]) for row in energy_rows) == pytest.approx(
        max(float(row["bess_soc_min_kwh"]) for row in bess_rows)
    )
    assert max(float(row["bess_soc_min_kwh"]) for row in energy_rows) == pytest.approx(expected["bess_soc_min_kwh"])
    assert max(float(row["bess_soc_max_kwh"]) for row in energy_rows) == pytest.approx(
        max(float(row["bess_soc_max_kwh"]) for row in bess_rows)
    )
    assert max(float(row["bess_soc_max_kwh"]) for row in energy_rows) == pytest.approx(expected["bess_soc_max_kwh"])
    if "bess_soc_start_kwh" in bess_rows[0]:
        assert [float(row["bess_soc_start_kwh"]) for row in energy_rows] == pytest.approx(
            [float(row["bess_soc_start_kwh"]) for row in bess_rows]
        )
        assert [float(row["bess_soc_end_kwh"]) for row in energy_rows] == pytest.approx(
            [float(row["bess_soc_end_kwh"]) for row in bess_rows]
        )
    else:
        assert [float(row["bess_soc_start_kwh"]) for row in energy_rows] == pytest.approx(
            [float(row["bess_soc_kwh"]) for row in bess_rows]
        )
        assert [float(row["bess_soc_end_kwh"]) for row in energy_rows] == pytest.approx(
            [float(row["bess_soc_kwh"]) for row in bess_rows]
        )
        validation_rows = read_rows(run_dir / "graph" / "data_flow_validation.csv")
        transition_check = next(
            row for row in validation_rows if row["check_name"] == "bess_soc_transition_balance"
        )
        assert transition_check["status"] == "SKIPPED"


def test_reporting_finalizer_preserves_explicit_bess_soc_transition(tmp_path) -> None:
    run_dir = tmp_path / "run"
    graph_dir = run_dir / "graph"
    graph_dir.mkdir(parents=True)
    energy_fields = ["slot_index", "timestamp", "depot_id"]
    with (graph_dir / "energy_flow_ledger.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=energy_fields)
        writer.writeheader()
        writer.writerow({"slot_index": 0, "timestamp": "2026-01-01T00:00:00", "depot_id": "dep-1"})
    bess_fields = [
        "date",
        "time",
        "depot_id",
        "bess_soc_kwh",
        "bess_soc_start_kwh",
        "bess_soc_end_kwh",
        "bess_soc_percent",
        "bess_soc_min_kwh",
        "bess_soc_max_kwh",
        "bess_terminal_soc_min_kwh",
    ]
    with (graph_dir / "bess_timeseries.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=bess_fields)
        writer.writeheader()
        writer.writerow(
            {
                "date": "2026-01-01",
                "time": "00:00",
                "depot_id": "dep-1",
                "bess_soc_kwh": 109.5,
                "bess_soc_start_kwh": 100.0,
                "bess_soc_end_kwh": 109.5,
                "bess_soc_percent": 54.75,
                "bess_soc_min_kwh": 20.0,
                "bess_soc_max_kwh": 180.0,
                "bess_terminal_soc_min_kwh": 100.0,
            }
        )
    (run_dir / "simulation_conditions.json").write_text(
        json.dumps(
            {
                "depot_energy_assets": [
                    {
                        "depot_id": "dep-1",
                        "bess_charge_efficiency": 0.95,
                        "bess_discharge_efficiency": 0.95,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    metadata = update_energy_flow_bess_metadata(run_dir)
    row = read_rows(graph_dir / "energy_flow_ledger.csv")[0]

    assert float(row["bess_soc_start_kwh"]) == 100.0
    assert float(row["bess_soc_end_kwh"]) == 109.5
    assert metadata["bess_efficiency_by_depot"]["dep-1"] == {
        "charge": 0.95,
        "discharge": 0.95,
    }
    assert metadata["bess_soc_transition_verifiable"] is True
    assert metadata["bess_soc_transition_source"] == "explicit_start_end_columns"
