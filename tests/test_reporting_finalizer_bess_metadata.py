from __future__ import annotations

import pytest

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
