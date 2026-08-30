from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools.thesis_authoring.validate_authoring_bundle import REQUIRED_FILES, validate_bundle


REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = REPO_ROOT / "docs/thesis/authoring_v1"


def read_power_rows(scenario: str) -> list[dict[str, str]]:
    path = BUNDLE / f"evidence_supplements/{scenario.lower()}_canonical_96_slot_power_series.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_bundle_has_required_files_and_traceable_sources() -> None:
    result = validate_bundle(REPO_ROOT)
    assert result["question_count"] >= 30
    assert result["claim_count"] >= 20
    assert result["equation_count"] >= 20
    assert all((BUNDLE / path).is_file() for path in REQUIRED_FILES)


@pytest.mark.parametrize(
    ("scenario", "expected_pv", "expected_grid", "expected_terminal"),
    (("SUNNY", 6056.25, 0.0, 3000.0), ("RAIN", 996.2, 130.85194331991343, 3000.0)),
)
def test_96_slot_series_reconciles_to_canonical_totals(
    scenario: str,
    expected_pv: float,
    expected_grid: float,
    expected_terminal: float,
) -> None:
    rows = read_power_rows(scenario)
    assert len(rows) == 96
    assert [int(row["slot_index"]) for row in rows] == list(range(96))
    assert sum(float(row["pv_generated_kwh"]) for row in rows) == pytest.approx(expected_pv, abs=1e-6)
    assert sum(float(row["grid_import_kwh"]) for row in rows) == pytest.approx(expected_grid, abs=1e-6)
    assert float(rows[-1]["bess_soc_end_kwh"]) == pytest.approx(expected_terminal, abs=1e-6)


def test_cost_difference_and_components_reconcile() -> None:
    source = json.loads((REPO_ROOT / "docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json").read_text(encoding="utf-8"))
    # The thesis-facing summary records the independently reconciled difference.
    results = source["scenarios"]
    sunny = results["SUNNY"]
    rain = results["RAIN"]
    total_difference = rain["executed_day_cost_jpy"] - sunny["executed_day_cost_jpy"]
    assert total_difference == pytest.approx(37614.8448386603, abs=1e-6)
    with (REPO_ROOT / "docs/thesis/weather_results_bb0c005/cost_breakdown.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        components = {row["source_key"]: float(row["RAIN_minus_SUNNY_jpy"]) for row in csv.DictReader(handle)}
    decomposed = components["fuel_cost"] + components["electricity_cost"] + components["co2_cost"]
    assert decomposed == pytest.approx(components["total_cost"], abs=1e-6)
    assert components["total_cost"] == pytest.approx(total_difference, abs=1e-6)


def test_manifest_payload_is_deterministic_before_write() -> None:
    first = validate_bundle(REPO_ROOT)
    second = validate_bundle(REPO_ROOT)
    assert first == second
