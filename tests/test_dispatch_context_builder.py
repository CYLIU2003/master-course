"""
tests/test_dispatch_context_builder.py

Tests for CSV -> DispatchContext conversion.
"""

from pathlib import Path

from src.dispatch.context_builder import load_dispatch_context_from_csv


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_context_filters_service_type_and_builds_profiles(tmp_path: Path):
    _write(
        tmp_path / "route_master" / "timetable.csv",
        "trip_id,route_id,direction,service_type,dep_time,arr_time,from_stop_id,to_stop_id,required_bus_type\n"
        "T1,R1,outbound,weekday,07:00,07:30,S1,S2,BEV\n"
        "T2,R1,outbound,holiday,08:00,08:30,S2,S3,ICE\n",
    )
    _write(
        tmp_path / "route_master" / "segments.csv",
        "segment_id,route_id,direction,from_stop_id,to_stop_id,distance_km\n"
        "seg_1,R1,outbound,S1,S2,12.5\n",
    )
    _write(
        tmp_path / "operations" / "vehicles.csv",
        "vehicle_id,vehicle_type,battery_capacity_kwh,efficiency_km_per_kwh\n"
        "bus_ev,BEV_large,300,1.2\n"
        "bus_ice,engine_bus,,\n",
    )
    _write(
        tmp_path / "operations" / "turnaround_rules.csv",
        "stop_id,min_turnaround_min\nS2,8\n",
    )
    _write(
        tmp_path / "operations" / "deadhead_rules.csv",
        "from_stop,to_stop,travel_time_min\nS2,S1,12\n",
    )

    ctx = load_dispatch_context_from_csv(
        data_dir=tmp_path,
        service_date="2024-06-01",
        service_type="weekday",
    )

    assert len(ctx.trips) == 1
    assert ctx.trips[0].trip_id == "T1"
    assert ctx.trips[0].allowed_vehicle_types == ("BEV",)
    assert round(ctx.trips[0].distance_km, 2) == 12.5

    assert "BEV" in ctx.vehicle_profiles
    assert "ICE" in ctx.vehicle_profiles
    assert ctx.turnaround_rules["S2"].min_turnaround_min == 8
    assert ctx.deadhead_rules[("S2", "S1")].travel_time_min == 12


def test_load_context_infers_alias_deadhead_for_same_coordinates(tmp_path: Path):
    _write(
        tmp_path / "route_master" / "timetable.csv",
        "trip_id,route_id,direction,dep_time,arr_time,from_stop_id,to_stop_id\n"
        "T1,R1,outbound,07:00,07:30,S_A,S_B\n",
    )
    _write(
        tmp_path / "route_master" / "stops.csv",
        "stop_id,lat,lon\nS_A,35.0,139.0\nS_A_IN,35.0,139.0\n",
    )

    ctx = load_dispatch_context_from_csv(data_dir=tmp_path, service_date="2024-06-01")

    assert ("S_A", "S_A_IN") in ctx.deadhead_rules
    assert ctx.deadhead_rules[("S_A", "S_A_IN")].travel_time_min == 1
