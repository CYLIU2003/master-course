from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path

from PIL import Image
import pytest

from scripts import build_thesis_weather_result_package as builder


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPO_ROOT / "docs" / "evidence" / "weather_dispatch_rerun_bb0c005"
EXPECTED_TREE_SHA256 = "c706da7e10bc4e99a06a441f91e1722baa971b41ab936d29db36e650accede5f"
EXPECTED_FIGURE_STEMS = (
    "01_used_vehicle_comparison",
    "02_assigned_trip_comparison",
    "03_executed_day_cost_breakdown",
    "04_pv_bess_grid_energy_balance",
    "05_pv_utilization_and_curtailment",
)
PROHIBITED_PHRASES = ("最適解", "大域最適", "1%以内", "雨天時の実運行")


def _hash_inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def generated_packages(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("thesis-weather-package")
    first = root / "first"
    second = root / "second"
    source_before = _hash_inventory(EVIDENCE_ROOT)
    builder.build_package(EVIDENCE_ROOT, first)
    builder.build_package(EVIDENCE_ROOT, second)
    assert _hash_inventory(EVIDENCE_ROOT) == source_before
    return first, second


def test_builder_loads_and_validates_both_canonical_scenarios() -> None:
    bundle = builder.load_and_validate_bundle(EVIDENCE_ROOT)

    assert bundle.tree_sha256 == EXPECTED_TREE_SHA256
    assert set(bundle.scenarios) == {"SUNNY", "RAIN"}
    assert bundle.summary["execution_git_sha"] == builder.EXECUTION_SHA
    assert bundle.input_contract["fixed_nonweather_inputs_equal"] is True

    sunny = bundle.scenarios["SUNNY"]
    rain = bundle.scenarios["RAIN"]
    assert sunny.summary["scenario_id"] == builder.SCENARIO_IDS["SUNNY"]
    assert rain.summary["scenario_id"] == builder.SCENARIO_IDS["RAIN"]
    assert sunny.summary["served_trips"] == rain.summary["served_trips"] == 264
    assert sunny.summary["unserved_trips"] == rain.summary["unserved_trips"] == 0
    assert sunny.summary["used_bev"] == 28
    assert sunny.summary["used_ice"] == 4
    assert rain.summary["used_bev"] == 21
    assert rain.summary["used_ice"] == 11
    assert sunny.costs["pv_generated_kwh"] == pytest.approx(6056.25)
    assert rain.costs["pv_generated_kwh"] == pytest.approx(996.2)
    assert sunny.rolling["step_count"] == rain.rolling["step_count"] == 24
    assert sunny.accounting["eligible"] is rain.accounting["eligible"] is True


def test_generated_package_is_byte_deterministic_and_complete(
    generated_packages: tuple[Path, Path],
) -> None:
    first, second = generated_packages
    assert _hash_inventory(first) == _hash_inventory(second)

    inventory = _hash_inventory(first)
    for stem in EXPECTED_FIGURE_STEMS:
        assert f"{stem}.png" in inventory
        assert f"{stem}.svg" in inventory
    assert not any(name.startswith("06_daily_energy_flow_timeseries") for name in inventory)
    for name in (
        "experiment_parameters.csv",
        "experiment_parameters.md",
        "scenario_results.csv",
        "scenario_results.md",
        "cost_breakdown.csv",
        "cost_breakdown.md",
        "energy_balance.csv",
        "energy_balance.md",
        "claim_boundary.md",
        "results_section_ja.md",
        "README.md",
        "package_manifest.json",
    ):
        assert name in inventory


def test_generated_tables_preserve_scenario_parameters_and_results(
    generated_packages: tuple[Path, Path],
) -> None:
    output, _ = generated_packages
    parameters = {
        (row["区分"], row["項目"]): row
        for row in _read_csv(output / "experiment_parameters.csv")
    }
    assert parameters[("運行", "営業所")]["共通値"] == "tsurumaki"
    assert parameters[("運行", "時刻表")]["共通値"] == "WEEKDAY"
    assert parameters[("運行", "運行日")]["共通値"] == "2025-08-05"
    assert parameters[("反実仮想", "気象・PV条件")]["RAIN"] == "2025-08-10由来の低PV曲線"
    assert parameters[("車両", "有効車両数")]["共通値"] == "60"
    assert parameters[("車両", "BEV／ICE在庫")]["共通値"] == "35／25"
    assert parameters[("充電", "充電器数")]["共通値"] == "10"
    assert parameters[("BESS", "初期／終端SOC")]["共通値"] == "3000／3000"
    assert parameters[("Solver", "Gurobi threads")]["共通値"] == "1"
    assert parameters[("Solver", "powertrain selector strengthening")]["共通値"] == "OFF"
    assert parameters[("充電", "受電上限")]["共通値"] == "正本bundleに明示値なし"
    assert parameters[("PV", "PV定格容量")]["共通値"] == "正本bundleに明示値なし"
    assert parameters[("BESS", "定格容量／出力")]["共通値"] == "正本bundleに明示値なし"

    scenarios = {row["scenario"]: row for row in _read_csv(output / "scenario_results.csv")}
    assert scenarios["SUNNY"]["scenario_id"] == builder.SCENARIO_IDS["SUNNY"]
    assert scenarios["RAIN"]["scenario_id"] == builder.SCENARIO_IDS["RAIN"]
    assert scenarios["SUNNY"]["rolling_steps"] == scenarios["RAIN"]["rolling_steps"] == "24/24"
    assert scenarios["SUNNY"]["physical_validation"] == scenarios["RAIN"]["physical_validation"] == "VALID"
    assert float(scenarios["SUNNY"]["executed_day_cost_jpy"]) == pytest.approx(660_983.7838045002)
    assert float(scenarios["RAIN"]["executed_day_cost_jpy"]) == pytest.approx(698_598.6286431606)

    energy = {row["scenario"]: row for row in _read_csv(output / "energy_balance.csv")}
    assert float(energy["SUNNY"]["bess_output_per_pv_input"]) == pytest.approx(0.95**2)
    assert float(energy["RAIN"]["bess_output_per_pv_input"]) == pytest.approx(0.95**2)
    assert energy["SUNNY"]["terminal_energy_balanced"] == energy["RAIN"]["terminal_energy_balanced"] == "True"


def test_generated_claims_and_figure_metadata_are_bounded(
    generated_packages: tuple[Path, Path],
) -> None:
    output, _ = generated_packages
    textual = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(output.iterdir())
        if path.suffix in {".md", ".csv", ".json", ".svg"}
    )
    for phrase in PROHIBITED_PHRASES:
        assert phrase not in textual
    assert "Stage 1の近似目的関数に対するcertified MIP gap" in textual
    assert "評価した有限候補集合から選択された、物理的・会計的に妥当なPhase 3二段階実行可能解" in textual
    assert "2025-08-05の平日運行へ2025-08-10由来の低PV曲線を与えた反実仮想" in textual

    results = (output / "results_section_ja.md").read_text(encoding="utf-8")
    compact_length = len("".join(results.split()))
    assert 1200 <= compact_length <= 2000

    manifest = json.loads((output / "package_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS"
    assert manifest["execution_git_sha"] == builder.EXECUTION_SHA
    assert manifest["source_bundle_tree_sha256"] == EXPECTED_TREE_SHA256
    assert manifest["png_dpi"] == 300
    assert manifest["timeseries_figure_created"] is False
    assert "No complete 96-slot" in manifest["timeseries_figure_omission_reason"]

    for stem in EXPECTED_FIGURE_STEMS:
        with Image.open(output / f"{stem}.png") as image:
            dpi = image.info.get("dpi")
            assert dpi is not None
            assert dpi[0] == pytest.approx(300, abs=0.1)
            assert dpi[1] == pytest.approx(300, abs=0.1)
            assert image.width > 1000
            assert image.height > 900
