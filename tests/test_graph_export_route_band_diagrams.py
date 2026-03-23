import json
import re
from datetime import date

from src.result_exporter import (
    _build_route_band_diagram_assets,
    _slot_to_iso,
    _write_route_band_diagram_assets,
)


def _timeline_row(
    *,
    vehicle_id: str,
    vehicle_type: str,
    state: str,
    start_time: str,
    end_time: str,
    from_location_id: str,
    to_location_id: str,
    band_id: str = "route/22",
    route_id: str = "",
    route_family_code: str = "FAM22",
    route_series_code: str = "route/22",
    event_route_band_id: str = "route/22",
    trip_id: str = "",
    refuel_liters: float = 0.0,
):
    return {
        "scenario_id": "scenario-1",
        "depot_id": "dep-1",
        "vehicle_id": vehicle_id,
        "vehicle_type": vehicle_type,
        "band_id": band_id,
        "band_label": band_id,
        "start_time": start_time,
        "end_time": end_time,
        "state": state,
        "route_id": route_id,
        "route_family_code": route_family_code,
        "route_series_code": route_series_code,
        "event_route_band_id": event_route_band_id,
        "trip_id": trip_id,
        "from_location_id": from_location_id,
        "to_location_id": to_location_id,
        "from_location_type": "terminal",
        "to_location_type": "terminal",
        "direction": "",
        "route_variant_type": "main",
        "energy_delta_kwh": 0.0,
        "distance_km": 0.0,
        "duration_min": 30.0,
        "is_deadhead": state == "deadhead",
        "is_charge": state == "charge",
        "is_service": state == "service",
        "is_idle": False,
        "is_depot_move": False,
        "is_short_turn": False,
        "charger_id": "chg-1" if state == "charge" else "",
        "charge_power_kw": 60.0 if state == "charge" else "",
        "refuel_liters": refuel_liters if state == "refuel" else "",
    }


def _svg_axis_labels(svg: str) -> list[str]:
    return re.findall(
        r'text-anchor="end" font-size="13"[^>]*>([^<]+)</text>',
        svg,
    )


def test_route_band_diagram_assets_emit_svg_and_manifest(tmp_path) -> None:
    rows = [
        _timeline_row(
            vehicle_id="veh-ev",
            vehicle_type="BEV",
            state="service",
            start_time="2026-03-23T08:00:00+09:00",
            end_time="2026-03-23T08:30:00+09:00",
            from_location_id="Depot 22",
            to_location_id="Stop C",
            route_id="r-1",
            trip_id="t-1",
        ),
        _timeline_row(
            vehicle_id="veh-ice",
            vehicle_type="ICE",
            state="deadhead",
            start_time="2026-03-23T08:32:00+09:00",
            end_time="2026-03-23T08:47:00+09:00",
            from_location_id="Stop C",
            to_location_id="Depot 22",
            route_id="",
            trip_id="",
            event_route_band_id="",
        ),
        _timeline_row(
            vehicle_id="veh-ice",
            vehicle_type="ICE",
            state="refuel",
            start_time="2026-03-23T08:48:00+09:00",
            end_time="2026-03-23T09:00:00+09:00",
            from_location_id="dep-1",
            to_location_id="dep-1",
            route_id="",
            trip_id="",
            event_route_band_id="",
            refuel_liters=18.0,
        ),
        _timeline_row(
            vehicle_id="veh-ice",
            vehicle_type="ICE",
            state="service",
            start_time="2026-03-23T09:00:00+09:00",
            end_time="2026-03-23T09:30:00+09:00",
            from_location_id="Stop C",
            to_location_id="Depot 22",
            route_id="r-2",
            trip_id="t-2",
        ),
        _timeline_row(
            vehicle_id="veh-ice",
            vehicle_type="ICE",
            state="service",
            start_time="2026-03-23T10:00:00+09:00",
            end_time="2026-03-23T10:20:00+09:00",
            from_location_id="Other 1",
            to_location_id="Other 2",
            band_id="route/99",
            route_id="r-99",
            route_family_code="FAM99",
            route_series_code="route/99",
            event_route_band_id="route/99",
            trip_id="t-3",
        ),
    ]
    graph_context = {
        "band_labels_by_band_id": {
            "route/22": "Route 22",
            "route/99": "Route 99",
        },
        "depot_labels_by_id": {
            "dep-1": "Depot 22",
        },
        "band_stop_sequences": {
            "route/22": [
                ["Depot 22", "Stop A", "Stop B", "Stop C"],
                ["Stop C", "Stop Bx", "Stop B", "Stop A", "Depot 22"],
            ],
            "route/99": [["Other 1", "Other 2"]],
        },
        "task_stop_sequences": {
            "t-1": [
                {"stop_label": "Depot 22", "departure_time": "08:00:00"},
                {"stop_label": "Stop A", "departure_time": "08:10:00"},
                {"stop_label": "Stop B", "departure_time": "08:20:00"},
                {"stop_label": "Stop C", "departure_time": "08:30:00"},
            ],
            "t-2": [
                {"stop_label": "Stop C", "departure_time": "09:00:00"},
                {"stop_label": "Stop Bx", "departure_time": "09:08:00"},
                {"stop_label": "Stop B", "departure_time": "09:10:00"},
                {"stop_label": "Stop A", "departure_time": "09:20:00"},
                {"stop_label": "Depot 22", "departure_time": "09:30:00"},
            ],
            "t-3": [
                {"stop_label": "Other 1", "departure_time": "10:00:00"},
                {"stop_label": "Other 2", "departure_time": "10:20:00"},
            ],
        },
    }

    assets = _build_route_band_diagram_assets(rows, "scenario-1", graph_context=graph_context)

    assert len(assets["entries"]) == 2
    entry = next(item for item in assets["entries"] if item["band_id"] == "route/22")
    assert entry["band_id"] == "route/22"
    assert entry["vehicle_count"] == 2
    assert entry["vehicle_type_counts"] == {"BEV": 1, "ICE": 1}
    assert entry["diagram_file"] == "route_22.svg"
    assert entry["shared_vehicle_ids"] == ["veh-ice"]
    assert entry["mixed_event_route_band_detected"] is True

    svg = assets["svg_payloads"]["route_22.svg"]
    assert "Route Band Diagram: Route 22" in svg
    assert "route-only stop axis / full-day 00:00-23:59 / depot stay inferred" in svg
    assert ">00:00<" in svg
    assert ">23:59<" in svg
    assert "Vehicle Types" in svg
    assert "Line Styles" in svg
    assert "veh-ev [BEV]" in svg
    assert "veh-ice [ICE]" in svg
    assert "Depot 22" in svg
    assert "Stop A" in svg
    assert "Stop B" in svg
    assert "Stop Bx" in svg
    assert "Stop C" in svg
    assert "Other 1" not in svg
    assert "Other 2" not in svg
    assert 'stroke-dasharray="8 5"' in svg
    assert "ICE refuel mark" in svg
    assert "#6cab2f" in svg
    axis_labels = _svg_axis_labels(svg)
    assert axis_labels in (
        ["Depot 22", "Stop A", "Stop B", "Stop Bx", "Stop C"],
        ["Stop C", "Stop Bx", "Stop B", "Stop A", "Depot 22"],
    )

    out_dir = tmp_path / "graph_exports"
    _write_route_band_diagram_assets(out_dir, assets)

    manifest = json.loads(
        (out_dir / "route_band_diagrams" / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_entry = next(item for item in manifest["entries"] if item["band_id"] == "route/22")
    assert manifest_entry["diagram_file"] == "route_22.svg"
    assert (out_dir / "route_band_diagrams" / "route_22.svg").exists()


def test_route_band_diagram_infers_depot_stay_rows() -> None:
    rows = [
        _timeline_row(
            vehicle_id="veh-1",
            vehicle_type="ICE",
            state="service",
            start_time="2026-03-23T08:00:00+09:00",
            end_time="2026-03-23T08:30:00+09:00",
            from_location_id="Stop A",
            to_location_id="Stop C",
            trip_id="t-1",
        ),
        _timeline_row(
            vehicle_id="veh-1",
            vehicle_type="ICE",
            state="service",
            start_time="2026-03-23T12:00:00+09:00",
            end_time="2026-03-23T12:30:00+09:00",
            from_location_id="Stop C",
            to_location_id="Stop A",
            trip_id="t-2",
        ),
    ]
    graph_context = {
        "band_labels_by_band_id": {"route/22": "Route 22"},
        "band_stop_sequences": {"route/22": [["Stop A", "Stop B", "Stop C"]]},
        "task_stop_sequences": {
            "t-1": [
                {"stop_label": "Stop A", "departure_time": "08:00:00"},
                {"stop_label": "Stop B", "departure_time": "08:15:00"},
                {"stop_label": "Stop C", "departure_time": "08:30:00"},
            ],
            "t-2": [
                {"stop_label": "Stop C", "departure_time": "12:00:00"},
                {"stop_label": "Stop B", "departure_time": "12:15:00"},
                {"stop_label": "Stop A", "departure_time": "12:30:00"},
            ],
        },
        "depot_labels_by_id": {"dep-1": "Depot 22"},
    }

    assets = _build_route_band_diagram_assets(rows, "scenario-1", graph_context=graph_context)

    svg = assets["svg_payloads"]["route_22.svg"]
    axis_labels = _svg_axis_labels(svg)
    assert axis_labels == ["Depot 22", "Stop A", "Stop B", "Stop C"]
    assert 'stroke-dasharray="2 6"' in svg
    assert 'stroke-dasharray="8 5"' in svg


def test_slot_to_iso_uses_planning_start_time() -> None:
    assert _slot_to_iso(date(2026, 3, 23), 0, 15, planning_start_time="05:00") == "2026-03-23T05:00:00+09:00"
    assert _slot_to_iso(date(2026, 3, 23), 70, 15, planning_start_time="05:00") == "2026-03-23T22:30:00+09:00"
