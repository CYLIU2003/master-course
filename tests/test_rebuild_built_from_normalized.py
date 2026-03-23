from __future__ import annotations

import pandas as pd

from scripts import rebuild_built_from_normalized as build_script


def test_build_trips_parquet_maps_by_odpt_pattern_id_without_family_replication() -> None:
    routes = [
        {
            "id": "route-main",
            "routeFamilyCode": "黒01",
            "depotId": "meguro",
            "odptPatternId": "odpt.BusroutePattern:TokyuBus.Kuro01.0004600634",
            "stopSequence": ["stop-meguro", "stop-oookayama"],
        },
        {
            "id": "route-short",
            "routeFamilyCode": "黒01",
            "depotId": "meguro",
            "odptPatternId": "odpt.BusroutePattern:TokyuBus.Kuro01.0004602004",
            "stopSequence": ["stop-meguro", "stop-oookayama"],
        },
        {
            "id": "route-return",
            "routeFamilyCode": "黒01",
            "depotId": "meguro",
            "odptPatternId": "odpt.BusroutePattern:TokyuBus.Kuro01.0004600713",
            "stopSequence": ["stop-shimizu", "stop-meguro-return"],
        },
    ]
    gtfs_trips = pd.DataFrame(
        [
            {
                "trip_id": "odpt.BusTimetable:TokyuBus.Kuro01.0004600634.Meguroekimae.00240480.3.Weekday.0609",
                "route_family": "黒01",
                "depot_id": "tokyu:depot:meguro",
                "calendar_type": "平日",
                "direction": "outbound",
                "departure": "06:09",
                "arrival": "06:58",
                "origin_id": "stop-meguro",
                "dest_id": "stop-oookayama",
                "origin_name": "目黒駅前",
                "dest_name": "大岡山小学校前",
                "origin_lat": None,
                "origin_lon": None,
                "dest_lat": None,
                "dest_lon": None,
            },
            {
                "trip_id": "odpt.BusTimetable:TokyuBus.Kuro01.0004602004.Meguroekimae.00240480.3.Weekday.2054",
                "route_family": "黒01",
                "depot_id": "tokyu:depot:meguro",
                "calendar_type": "平日",
                "direction": "outbound",
                "departure": "20:54",
                "arrival": "21:24",
                "origin_id": "stop-meguro",
                "dest_id": "stop-oookayama",
                "origin_name": "目黒駅前",
                "dest_name": "大岡山小学校前",
                "origin_lat": None,
                "origin_lon": None,
                "dest_lat": None,
                "dest_lon": None,
            },
            {
                "trip_id": "odpt.BusTimetable:TokyuBus.Kuro01.0004600713.Shimizu.00240485.b.Weekday.0543",
                "route_family": "黒01",
                "depot_id": "tokyu:depot:meguro",
                "calendar_type": "平日",
                "direction": "inbound",
                "departure": "05:43",
                "arrival": "05:59",
                "origin_id": "stop-shimizu",
                "dest_id": "stop-meguro-return",
                "origin_name": "清水",
                "dest_name": "目黒駅前",
                "origin_lat": None,
                "origin_lon": None,
                "dest_lat": None,
                "dest_lon": None,
            },
        ]
    )

    trips_df = build_script.build_trips_parquet(
        gtfs_trips,
        build_script.build_pattern_lookup(routes),
        build_script.build_odpt_route_lookup(routes),
        build_script.build_route_family_lookup_no_depot(routes),
    )

    assert trips_df["route_id"].tolist() == ["route-main", "route-short", "route-return"]
    assert not trips_df["trip_id"].astype(str).str.contains(r"__v\d+$", regex=True).any()
    assert len(trips_df) == 3
