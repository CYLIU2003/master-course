from __future__ import annotations

import json

import pytest

from bff.services.local_db_catalog import _pattern_distance_km
from bff.store import desktop_store
from src.geo import haversine_km


def test_pattern_distance_uses_each_adjacent_stop_and_rejects_missing_coordinates():
    stops = [
        {"lat": 35.0, "lon": 139.0},
        {"lat": 35.01, "lon": 139.0},
        {"lat": 35.01, "lon": 139.01},
    ]
    expected = haversine_km(35.0, 139.0, 35.01, 139.0) + haversine_km(35.01, 139.0, 35.01, 139.01)
    assert _pattern_distance_km(stops) == pytest.approx(expected, abs=1e-6)
    assert _pattern_distance_km([stops[0], {"lat": None, "lon": 139.0}]) is None
    assert _pattern_distance_km([stops[0], {"lat": float("nan"), "lon": 139.0}]) is None


def test_scenario_route_catalog_keeps_unassigned_and_incomplete_routes_visible(monkeypatch):
    monkeypatch.setattr(desktop_store, "_display_stop_catalog", lambda: {})
    collections = {
        "depots": [{"id": "d", "name": "Depot"}],
        "routes": [
            {"id": "r1", "routeCode": "R", "depotId": "d", "stopSequence": ["a", "b", "c"]},
            {"id": "r2", "routeCode": "X", "stopSequence": ["a", "missing"]},
        ],
        "stops": [
            {"id": "a", "name": "A", "lat": 35.0, "lon": 139.0},
            {"id": "b", "name": "B", "lat": 35.01, "lon": 139.0},
            {"id": "c", "name": "C", "lat": 35.01, "lon": 139.01},
        ],
        "route_depot_assignments": [],
    }
    monkeypatch.setattr(desktop_store, "collection", lambda _id, name: collections[name])
    result = desktop_store.route_catalog("scenario")
    assert result["routes"][0]["depotIds"] == ["d"]
    assert result["routes"][0]["distanceKm"] == _pattern_distance_km([
        {"lat": 35.0, "lon": 139.0}, {"lat": 35.01, "lon": 139.0}, {"lat": 35.01, "lon": 139.01},
    ])
    assert result["routes"][1]["depotIds"] == []
    assert result["routes"][1]["distanceKm"] is None


def test_scenario_route_catalog_labels_supplemental_coordinates(monkeypatch):
    stop_id = "odpt.BusstopPole:test"
    collections = {
        "depots": [],
        "routes": [{"id": "r", "source": "odpt", "stopSequence": [stop_id, "odpt.BusstopPole:next"]}],
        "stops": [{"id": stop_id, "name": "A", "lat": 35.0, "lon": 139.0}],
        "route_depot_assignments": [],
    }
    monkeypatch.setattr(desktop_store, "collection", lambda _id, name: collections[name])
    monkeypatch.setattr(desktop_store, "_display_stop_catalog", lambda: {
        "odpt.BusstopPole:next": {"id": "odpt.BusstopPole:next", "name": "B", "lat": 35.01, "lon": 139.0},
    })
    route = desktop_store.route_catalog("scenario")["routes"][0]
    assert route["distanceKm"] == pytest.approx(haversine_km(35, 139, 35.01, 139), abs=1e-6)
    assert route["distanceSource"] == "catalog_fast_stop_sequence_haversine_display_only"
    assert route["stops"][1]["coordinateSource"] == "catalog_fast_display_only"


def test_odpt_route_catalog_projects_frozen_routes_without_editing_inputs(monkeypatch, tmp_path):
    root = tmp_path / "data"
    catalog_dir = root / "catalog-fast" / "tokyu_bus_data"
    catalog_dir.mkdir(parents=True)
    depot_dir = root / "seed" / "tokyu"
    depot_dir.mkdir(parents=True)
    original_route = {
        "id": "r", "name": "Route", "routeFamilyCode": "R", "depotId": "d",
        "source": "odpt", "stopSequence": ["a", "b"], "distanceKm": 0,
        "tripCount": 3, "tripCountsByDayType": {"WEEKDAY": 3},
        "firstDepartureByDayType": {"WEEKDAY": "06:00"},
        "lastArrivalByDayType": {"WEEKDAY": "22:00"},
        "odptPatternId": "odpt.BusroutePattern:test",
        "routeVariantTypeManual": "main", "classificationSource": "manual_override",
    }
    (catalog_dir / "routes.jsonl").write_text(json.dumps(original_route) + "\n", encoding="utf-8")
    (catalog_dir / "network_summary.json").write_text(json.dumps({"sourceSnapshotId": "snapshot"}), encoding="utf-8")
    (depot_dir / "depots.json").write_text(json.dumps({"depots": [{"id": "d", "name": "Depot"}]}), encoding="utf-8")
    monkeypatch.setattr(desktop_store, "project_root", lambda: tmp_path)
    monkeypatch.setattr(desktop_store, "_display_stop_catalog", lambda: {
        "a": {"id": "a", "name": "A", "lat": 35.0, "lon": 139.0},
        "b": {"id": "b", "name": "B", "lat": 35.01, "lon": 139.0},
    })

    result = desktop_store.odpt_route_catalog()
    route = result["routes"][0]
    assert result["sourceSnapshotId"] == "snapshot"
    assert route["depotIds"] == ["d"]
    assert route["distanceKm"] == pytest.approx(haversine_km(35, 139, 35.01, 139), abs=1e-6)
    assert route["storedDistanceKm"] == 0
    assert route["tripCountsByDayType"] == {"WEEKDAY": 3}
    assert route["firstDepartureByDayType"] == {"WEEKDAY": "06:00"}
    assert route["lastArrivalByDayType"] == {"WEEKDAY": "22:00"}
    assert route["odptPatternId"] == "odpt.BusroutePattern:test"
    assert route["classificationSource"] == "manual_override"
    assert json.loads((catalog_dir / "routes.jsonl").read_text(encoding="utf-8")) == original_route


def test_odpt_official_depot_reference_is_display_only(monkeypatch, tmp_path):
    catalog_dir = tmp_path / "data" / "catalog-fast" / "tokyu_bus_data"
    catalog_dir.mkdir(parents=True)
    (catalog_dir / "routes.jsonl").write_text(
        json.dumps({"id": "r", "routeFamilyCode": "日51", "source": "odpt", "stopSequence": []}) + "\n",
        encoding="utf-8",
    )
    summary_path = catalog_dir / "network_summary.json"
    summary_path.write_text(json.dumps({"sourceSnapshotId": "snapshot"}), encoding="utf-8")
    depot_dir = tmp_path / "data" / "seed" / "tokyu"
    depot_dir.mkdir(parents=True)
    (depot_dir / "depots.json").write_text(
        json.dumps({"depots": [{"id": "nippa", "name": "新羽営業所"}]}), encoding="utf-8",
    )
    reference_dir = tmp_path / "data" / "reference"
    reference_dir.mkdir(parents=True)
    (reference_dir / "tokyu_route_depot_reference_20260925.json").write_text(json.dumps({
        "capturedAt": "2026-09-25",
        "sourceSnapshotId": "snapshot",
        "groups": [{
            "depotId": "nippa", "routeCodes": ["日51"],
            "sourceUrl": "https://www.tokyubus.co.jp/route/routemap/pdf/09_nippa.pdf",
            "sourceDate": "2026-04-01",
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(desktop_store, "project_root", lambda: tmp_path)
    monkeypatch.setattr(desktop_store, "_display_stop_catalog", lambda: {})

    route = desktop_store.odpt_route_catalog()["routes"][0]
    assert route["depotIds"] == []
    assert route["officialDepotReference"]["depotId"] == "nippa"
    assert route["officialDepotReference"]["sourceDate"] == "2026-04-01"
    assert "depotId" not in json.loads((catalog_dir / "routes.jsonl").read_text(encoding="utf-8"))
    summary_path.write_text(json.dumps({"sourceSnapshotId": "different"}), encoding="utf-8")
    mismatched = desktop_store.odpt_route_catalog()
    assert mismatched["officialReferenceStatus"] == "snapshot_mismatch"
    assert "officialDepotReference" not in mismatched["routes"][0]
