"""Regression checks for the descriptive deck and its disclosed SOC finding."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "outcome/2026-09-07_urabe_progress_review"
DECK = PACKAGE / "archive/progress_with_urabe_supplement_20260907_final.pptx"
pytestmark = pytest.mark.skipif(not DECK.exists(), reason="Local review artifact not generated")
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}


@pytest.fixture(scope="module")
def data():
    return json.loads((PACKAGE / "analysis/review_data.json").read_text(encoding="utf-8"))


def test_all_bound_sources_remain_unchanged(data):
    for file, expected in data["source_sha256"].items():
        assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == expected, file
    assert data["solver_runs"] == 0
    assert data["execution_sha"].startswith("bb0c005")


@pytest.mark.parametrize("scenario", ["SUNNY", "RAIN"])
def test_prefixes_reconcile_to_unique_final_ledger(data, scenario):
    s = data["scenarios"][scenario]
    rows, cost = s["slots"], s["accounting"]["cost_breakdown"]
    assert [row["slot_index"] for row in rows] == list(range(96))
    for field in ["pv_generated_kwh", "pv_to_bus_kwh", "pv_to_bess_kwh",
                  "pv_curtailed_kwh", "bess_to_bus_kwh", "grid_import_kwh"]:
        assert sum(row[field] for row in rows) == pytest.approx(cost[field], abs=1e-6)
    for row in rows:
        assert row["charging_kw"] / 4 == pytest.approx(row["bev_charging_load_kwh"], abs=1e-6)
    assert cost["total_cost"] == pytest.approx(sum(cost[k] for k in
        ["vehicle_usage_cost", "fuel_cost", "electricity_cost", "co2_cost"]), abs=1e-6)
    assert cost["vehicle_usage_cost"] == 32 * 20000
    assert rows[-1]["bess_soc_end_kwh"] == pytest.approx(3000, abs=1e-6)


@pytest.mark.parametrize("scenario,run", [("SUNNY", "1445"), ("RAIN", "1455")])
def test_bev_soc_start_and_terminal_semantics(data, scenario, run):
    e = data["scenarios"][scenario]["example"]
    raw = ROOT / f"output/2026-08-29/run_20260829_{run}/rolling_hourly_chain"
    first = json.loads((raw / "step_00_0000/hourly_solver_result.json").read_text())
    last = json.loads((raw / "step_23_2300/hourly_solver_result.json").read_text())
    assert len(e["soc_kwh"]) == 97
    assert e["soc_kwh"][0] == first["vehicle_soc_kwh_by_vehicle_slot"][e["vehicle_id"]]["0"]
    assert e["soc_kwh"][95] == last["vehicle_soc_kwh_by_vehicle_slot"][e["vehicle_id"]]["95"]
    assert e["soc_kwh"][96] == last["solver_metadata"]["vehicle_terminal_soc_kwh_by_vehicle"][e["vehicle_id"]]
    assert e["soc_kwh"][-1] == pytest.approx(e["soc_kwh"][0], abs=1e-6)


def test_prepared_upper_bound_failure_is_not_hidden(data):
    sunny = data["scenarios"]["SUNNY"]["prepared_soc_upper_audit"]
    rain = data["scenarios"]["RAIN"]["prepared_soc_upper_audit"]
    assert sunny["status"] == "FAIL"
    assert sunny["affected_vehicle_count"] == 3
    assert sunny["exceedance_count"] == 12
    assert sunny["maximum_soc_percent"] == pytest.approx(93.37470112101911)
    assert rain["exceedance_count"] == 0
    assert "NOT USED FOR RESEARCH CONCLUSIONS" in data["research_use_status"]
    assert "PREPARED_MAX_SOC_NOT_ENFORCED_IN_FROZEN_STAGE2" in data["blocking_reasons"]


def test_editable_evidence_notes_and_disclosures():
    manifest = json.loads((PACKAGE / "analysis/presentation_manifest.json").read_text())
    assert manifest["total_slides"] == 35
    assert manifest["supplement_slides"] == 17
    assert manifest["final_sha256"] == hashlib.sha256(DECK.read_bytes()).hexdigest()
    with zipfile.ZipFile(DECK) as z:
        slides = [name for name in z.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
        assert len(slides) == 35
        for number in range(1, 36):
            xml = ET.fromstring(z.read(f"ppt/slides/slide{number}.xml"))
            text = " ".join(xml.itertext())
            assert "DIAGNOSTIC" in text
            assert "NOT USED FOR RESEARCH CONCLUSIONS" in text
            notes = z.read(f"ppt/notesSlides/notesSlide{number}.xml").decode()
            assert "SOC" in notes
            assert "[object Object]" not in notes
        for number in manifest["native_table_slides"]:
            assert ET.fromstring(z.read(f"ppt/slides/slide{number}.xml")).findall(".//a:tbl", NS)
        for number in manifest["native_chart_slides"]:
            assert ET.fromstring(z.read(f"ppt/slides/slide{number}.xml")).findall(".//c:chart", NS)
        assert any(name.startswith("ppt/embeddings/") and name.endswith(".xlsx") for name in z.namelist())
        assert "93.375%" in z.read("ppt/slides/slide35.xml").decode()
