from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

import scripts.benchmarks.prepare_shibu21_24_seasonal_inputs as inputs


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_three_route_source(root: Path) -> None:
    routes = []
    rows = []
    sequences = []
    stops = []
    for number in (21, 22, 23):
        route_id = f"route-{number}"
        trip_id = f"trip-{number}"
        first_stop = f"stop-{number}-a"
        last_stop = f"stop-{number}-b"
        routes.append({
            "id": route_id,
            "routeCode": f"渋{number:d}".replace(str(number), str(number).translate(str.maketrans("0123456789", "０１２３４５６７８９"))),
            "routeSeriesNumber": number,
            "odptBusrouteId": f"odpt.Busroute:TokyuBus.Shibu{number}",
        })
        rows.append({
            "trip_id": trip_id,
            "route_id": route_id,
            "routeCode": f"渋{number:d}".replace(str(number), str(number).translate(str.maketrans("0123456789", "０１２３４５６７８９"))),
            "operator_id": "tokyu",
            "distance_km": 5.0,
            "distance_source": "test_source",
        })
        sequences.extend([
            {"trip_id": trip_id, "stop_id": first_stop},
            {"trip_id": trip_id, "stop_id": last_stop},
        ])
        stops.extend([
            {"id": first_stop, "name": first_stop, "lat": 35.0, "lon": 139.0, "operator_id": "tokyu"},
            {"id": last_stop, "name": last_stop, "lat": 35.1, "lon": 139.1, "operator_id": "tokyu"},
        ])
    _write_json(root / "selected_routes.json", routes)
    _write_json(root / "timetable_rows.json", rows)
    _write_json(root / "stop_sequences.json", sequences)
    _write_json(root / "stops.json", list(reversed(stops)))
    _write_json(root / "manifest.json", {"source": "test"})


def test_three_route_scope_is_exact_and_does_not_read_route24(tmp_path, monkeypatch) -> None:
    old_source = tmp_path / "old"
    _write_three_route_source(old_source)
    monkeypatch.setattr(inputs, "ROOT", tmp_path)
    monkeypatch.setattr(inputs, "OLD_SOURCE_DIR", old_source)
    monkeypatch.setattr(
        inputs,
        "THREE_ROUTE_SOURCE_CANDIDATE_DIR",
        tmp_path / "three_route_output",
    )
    monkeypatch.setattr(
        inputs,
        "SHIBU24_SOURCE_DIR",
        tmp_path / "route24_that_must_not_be_read",
    )
    source_snapshot = {
        name: json.loads((old_source / name).read_text(encoding="utf-8"))
        for name in (
            "selected_routes.json", "timetable_rows.json",
            "stop_sequences.json", "stops.json"
        )
    }

    manifest = inputs.build_source_candidate(route_codes=inputs.THREE_ROUTE_CODES)

    assert manifest["route_codes"] == ["渋21", "渋22", "渋23"]
    assert manifest["route_count"] == 3
    assert manifest["trip_count"] == 3
    assert manifest["source_id"] == inputs.THREE_ROUTE_SOURCE_ID
    assert manifest["source_directory"] == "three_route_output"
    assert manifest["distance_semantics"]
    assert manifest["input_source_sha256"]
    assert (tmp_path / "three_route_output" / "manifest.json").is_file()
    for name, content in source_snapshot.items():
        assert json.loads(
            (tmp_path / "three_route_output" / name).read_text(encoding="utf-8")
        ) == content

    with pytest.raises(FileExistsError):
        inputs.build_source_candidate(route_codes=inputs.THREE_ROUTE_CODES)


def test_three_route_scope_rejects_any_route_outside_declared_set() -> None:
    with pytest.raises(ValueError, match="exact 渋21/渋22/渋23 scope"):
        inputs._validated_route_codes(("渋21", "渋22", "渋24"))


def test_campaign_loads_only_declared_frozen_source_and_rejects_drift(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    _write_three_route_source(raw)
    monkeypatch.setattr(inputs, "ROOT", tmp_path)
    monkeypatch.setattr(inputs, "OLD_SOURCE_DIR", raw)
    candidate = tmp_path / "candidate"
    inputs.build_source_candidate(route_codes=inputs.THREE_ROUTE_CODES,
                                  output_directory=candidate)
    manifest_sha = hashlib.sha256((candidate / "manifest.json").read_bytes()).hexdigest()
    monkeypatch.setattr(inputs, "OLD_SOURCE_DIR", tmp_path / "missing_raw_source")
    loaded = inputs.load_source_candidate(
        candidate, route_codes=inputs.THREE_ROUTE_CODES, manifest_sha256=manifest_sha)
    assert loaded["source_directory"] == "candidate"
    with pytest.raises(ValueError, match="manifest hash changed"):
        inputs.load_source_candidate(candidate, route_codes=inputs.THREE_ROUTE_CODES,
                                     manifest_sha256="0" * 64)
    (candidate / "timetable_rows.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact changed"):
        inputs.load_source_candidate(candidate, route_codes=inputs.THREE_ROUTE_CODES,
                                     manifest_sha256=manifest_sha)


def test_custom_source_namespace_rejects_overwrite_and_escape(tmp_path, monkeypatch):
    old = tmp_path / "raw"
    _write_three_route_source(old)
    monkeypatch.setattr(inputs, "ROOT", tmp_path)
    monkeypatch.setattr(inputs, "OLD_SOURCE_DIR", old)
    output = tmp_path / "campaign/source_candidate"
    inputs.build_source_candidate(route_codes=inputs.THREE_ROUTE_CODES, output_directory=output)
    snapshot = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(FileExistsError):
        inputs.build_source_candidate(route_codes=inputs.THREE_ROUTE_CODES, output_directory=output)
    with pytest.raises(ValueError):
        inputs.build_source_candidate(route_codes=inputs.THREE_ROUTE_CODES,
                                      output_directory=tmp_path / "../escaped_candidate")
    assert {p.name: p.read_bytes() for p in output.iterdir()} == snapshot


def test_route_matching_accepts_source_route_number_provenance() -> None:
    row = {
        "routeCode": "渋２３",
        "routeSeriesNumber": 23,
        "odptBusrouteId": "odpt.Busroute:TokyuBus.Shibu23",
    }

    assert inputs._matches_route_code(row, "渋23")
    assert not inputs._matches_route_code(row, "渋22")


@pytest.mark.parametrize(
    "row",
    [
        {"routeCode": "上21"},
        {"routeCode": "渋210"},
        {"routeSeriesNumber": 21, "odptBusrouteId": "TokyuBus.Shibu21"},
    ],
)
def test_route_matching_rejects_similar_labels_and_identifier_only_rows(row: dict) -> None:
    assert not inputs._matches_route_code(row, "渋21")
