"""Check the local, editable August deck against its frozen evidence sources."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import posixpath
import zipfile
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "outcome/2026-09-05_august_progress_revision"
DECK = PACKAGE / "august_progress_revised_20260905.pptx"
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
pytestmark = pytest.mark.skipif(not DECK.exists(), reason="Local Outcome artifact not generated")


def read_csv(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def charts_for_slide(number: int) -> list[ET.Element]:
    with zipfile.ZipFile(DECK) as archive:
        slide = ET.fromstring(archive.read(f"ppt/slides/slide{number}.xml"))
        relationships = ET.fromstring(archive.read(f"ppt/slides/_rels/slide{number}.xml.rels"))
        targets = {row.attrib["Id"]: row.attrib["Target"] for row in relationships}
        parts = [posixpath.normpath(posixpath.join("ppt/slides", targets[chart.attrib[f'{{{NS["r"]}}}id']]))
                 for chart in slide.findall(".//c:chart", NS)]
        # OPC relationships may use package-absolute or source-relative targets.
        return [ET.fromstring(archive.read(part.lstrip("/"))) for part in parts]


def values(series: ET.Element, component: str) -> list[float]:
    return [float(point.text) for point in series.findall(f"c:{component}//c:pt/c:v", NS)]


def test_original_and_all_bound_sources_unchanged():
    manifest = json.loads((PACKAGE / "source_manifest.json").read_text(encoding="utf-8"))
    original = Path(manifest["source_pptx"])
    assert hashlib.sha256(original.read_bytes()).hexdigest() == manifest["source_sha256"]
    assert manifest["solver_runs"] == 0
    for relative, expected in manifest["sources"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative


def test_native_objects_notes_and_slide_count():
    with zipfile.ZipFile(DECK) as archive:
        document = ET.fromstring(archive.read("ppt/presentation.xml"))
        assert len(document.findall("p:sldIdLst/p:sldId", NS)) == 22
        assert len([name for name in archive.namelist() if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")]) == 22
        for number in [3, 6, 7, 8, 9, 15, 16, 17, 19, 20, 22]:
            slide = ET.fromstring(archive.read(f"ppt/slides/slide{number}.xml"))
            assert slide.find(".//a:tbl", NS) is not None
    assert [len(charts_for_slide(number)) for number in [10, 11, 12, 14, 21]] == [2, 1, 1, 2, 1]


def test_dispatch_chart_preserves_all_trips_and_vehicles():
    actual = [[values(series, "val") for series in chart.findall(".//c:ser", NS)]
              for chart in charts_for_slide(10)]
    assert actual == [[[28, 21], [4, 11]], [[199, 91], [65, 173]]]


def test_candidate_chart_matches_hash_paired_diagnostic_matrix():
    candidates = read_csv("docs/thesis/authoring_v1/tables/cross_weather_candidate_analysis.csv")
    matrix = read_csv("docs/evidence/weather_dispatch_rerun_bb0c005/cross_weather_fixed_dispatch_matrix.csv")
    paired = {(row["assignment_hash"], row["scenario"]): float(row["canonical_actual_cost_jpy"]) for row in matrix}
    assert len(candidates) == 22 and len(paired) == 44
    candidates.sort(key=lambda row: int(row["used_bev"]))
    series = charts_for_slide(11)[0].findall(".//c:ser", NS)
    for name, curve in zip(["SUNNY", "RAIN"], series, strict=True):
        expected = [paired[(row["physical_assignment_sha256"], name)] / 1000 for row in candidates]
        assert values(curve, "xVal") == [int(row["used_bev"]) for row in candidates]
        assert values(curve, "yVal") == pytest.approx(expected, abs=5.1e-7, rel=0)


def test_cost_chart_uses_executed_accounting_not_day_ahead():
    data = json.loads((ROOT / "outcome/2026-09-05_research_progress/analysis/summary.json").read_text(encoding="utf-8"))
    series = charts_for_slide(12)[0].findall(".//c:ser", NS)
    for curve, key in zip(series, ["fuel_jpy", "electricity_jpy", "co2_jpy"], strict=True):
        assert values(curve, "val") == pytest.approx([row[key] for row in data["costs"]], abs=5.1e-7, rel=0)


@pytest.mark.parametrize("index,scenario", [(0, "SUNNY"), (1, "RAIN")])
def test_96_slot_chart_converts_interval_energy_to_average_power(index, scenario):
    rows = [row for row in read_csv("outcome/2026-09-05_research_progress/analysis/executed_slots.csv") if row["scenario"] == scenario]
    series = charts_for_slide(14)[index].findall(".//c:ser", NS)
    assert len(rows) == 96
    for curve, key in zip(series, ["pv_generated_kwh", "bev_charging_load_kwh", "pv_curtailed_kwh"], strict=True):
        assert values(curve, "xVal") == [number / 4 for number in range(96)]
        assert values(curve, "yVal") == pytest.approx([float(row[key]) * 4 for row in rows], abs=5.1e-7, rel=0)


def test_bess_chart_includes_initial_and_96_terminal_states():
    rows = read_csv("outcome/2026-09-05_research_progress/analysis/executed_slots.csv")
    series = charts_for_slide(21)[0].findall(".//c:ser", NS)
    for scenario, curve in zip(["SUNNY", "RAIN"], series, strict=True):
        expected = [3000] + [float(row["bess_soc_end_kwh"]) for row in rows if row["scenario"] == scenario]
        assert values(curve, "xVal") == [number / 4 for number in range(97)]
        assert values(curve, "yVal") == pytest.approx(expected, abs=5.1e-7, rel=0)
        assert expected[-1] == pytest.approx(3000, abs=1e-6)
