from __future__ import annotations

import json

from src.result_exporter import (
    _build_vehicle_operation_diagram_assets,
    _filter_timeline_rows_for_day,
    _write_vehicle_operation_diagram_assets,
)


def _timeline_row(
    *,
    vehicle_id: str,
    vehicle_type: str,
    state: str,
    start_time: str,
    end_time: str,
    band_label: str = "",
    band_id: str = "",
    route_id: str = "",
    route_family_code: str = "",
    trip_id: str = "",
    charge_power_kw: float = 0.0,
    refuel_liters: float = 0.0,
):
    return {
        "scenario_id": "scenario-1",
        "vehicle_id": vehicle_id,
        "vehicle_type": vehicle_type,
        "state": state,
        "event_type": state,
        "start_time": start_time,
        "end_time": end_time,
        "band_label": band_label,
        "band_id": band_id,
        "route_id": route_id,
        "route_family_code": route_family_code,
        "trip_id": trip_id,
        "charge_power_kw": charge_power_kw,
        "refuel_liters": refuel_liters,
    }


def test_vehicle_operation_diagram_assets_emit_svg_and_manifest(tmp_path) -> None:
    rows = [
        _timeline_row(
            vehicle_id="veh-ev",
            vehicle_type="BEV",
            state="service",
            start_time="2026-03-23T08:00:00+09:00",
            end_time="2026-03-23T08:30:00+09:00",
            band_label="渋24",
            band_id="渋24",
            route_family_code="渋24",
            route_id="route-24",
            trip_id="t-1",
        ),
        _timeline_row(
            vehicle_id="veh-ev",
            vehicle_type="BEV",
            state="deadhead",
            start_time="2026-03-23T08:30:00+09:00",
            end_time="2026-03-23T08:45:00+09:00",
        ),
        _timeline_row(
            vehicle_id="veh-ev",
            vehicle_type="BEV",
            state="charge",
            start_time="2026-03-23T09:00:00+09:00",
            end_time="2026-03-23T09:30:00+09:00",
            charge_power_kw=60.0,
        ),
        _timeline_row(
            vehicle_id="veh-ice",
            vehicle_type="ICE",
            state="service",
            start_time="2026-03-23T10:00:00+09:00",
            end_time="2026-03-23T10:25:00+09:00",
            band_label="渋23",
            band_id="渋23",
            route_family_code="渋23",
            route_id="route-23",
            trip_id="t-2",
        ),
        _timeline_row(
            vehicle_id="veh-ice",
            vehicle_type="ICE",
            state="refuel",
            start_time="2026-03-23T10:25:00+09:00",
            end_time="2026-03-23T10:35:00+09:00",
            refuel_liters=24.0,
        ),
    ]

    assets = _build_vehicle_operation_diagram_assets(rows, "scenario-1")

    assert len(assets["entries"]) == 1
    entry = assets["entries"][0]
    assert entry["diagram_file"] == "all_vehicles.svg"
    assert entry["vehicle_count"] == 2
    assert entry["state_counts"] == {
        "service": 2,
        "deadhead": 1,
        "charge": 1,
        "refuel": 1,
    }

    svg = assets["svg_payloads"]["all_vehicles.svg"]
    assert "Vehicle Operation Diagram: All Vehicles" in svg
    assert "veh-ev [BEV]" in svg
    assert "veh-ice [ICE]" in svg
    assert "渋24" in svg
    assert "渋23" in svg
    assert "回送" in svg
    assert "充電 60kW" in svg
    assert ">00:00<" in svg
    assert ">23:59<" in svg

    out_dir = tmp_path / "graph_exports"
    _write_vehicle_operation_diagram_assets(out_dir, assets)

    manifest = json.loads(
        (out_dir / "vehicle_operation_diagrams" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["entries"][0]["diagram_file"] == "all_vehicles.svg"
    assert (out_dir / "vehicle_operation_diagrams" / "all_vehicles.svg").exists()


def test_filter_timeline_rows_for_day_supports_iso_datetime_multi_day() -> None:
    rows = [
        _timeline_row(
            vehicle_id="veh-1",
            vehicle_type="BEV",
            state="service",
            start_time="2026-03-23T23:10:00+09:00",
            end_time="2026-03-23T23:40:00+09:00",
            band_label="route-a",
        ),
        _timeline_row(
            vehicle_id="veh-1",
            vehicle_type="BEV",
            state="service",
            start_time="2026-03-24T01:30:00+09:00",
            end_time="2026-03-24T02:00:00+09:00",
            band_label="route-b",
        ),
    ]

    day_rows = _filter_timeline_rows_for_day(rows, 1, 30)

    assert len(day_rows) == 1
    assert day_rows[0]["band_label"] == "route-b"
    assert day_rows[0]["start_minute"] == 90
    assert day_rows[0]["end_minute"] == 120
