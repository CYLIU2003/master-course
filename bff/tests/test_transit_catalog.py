from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bff.services import transit_catalog
from bff.services.odpt_routes import DEFAULT_OPERATOR


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class TransitCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp_path = Path(self.tmpdir.name)

        self.env = patch.dict(
            os.environ,
            {
                "TRANSIT_CATALOG_DB_PATH": str(self.tmp_path / "transit_catalog.sqlite"),
                "ODPT_SNAPSHOT_DIR": str(self.tmp_path / "odpt_saved"),
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_odpt_uses_saved_snapshot_before_remote_refresh(self) -> None:
        saved_dir = self.tmp_path / "odpt_saved"
        _write_json(saved_dir / "operational_dataset.json", self._sample_odpt_operational())

        with patch(
            "bff.services.transit_catalog.fetch_operational_dataset",
            side_effect=AssertionError("remote refresh should not run"),
        ):
            first_bundle = transit_catalog.get_or_refresh_odpt_snapshot(
                operator=DEFAULT_OPERATOR,
                dump=False,
                force_refresh=False,
            )

        self.assertEqual(first_bundle["meta"]["snapshotMode"], "saved-json")
        self.assertEqual(first_bundle["meta"]["snapshotSource"], "saved-json")
        self.assertEqual(len(first_bundle["stops"]), 2)
        self.assertEqual(len(first_bundle["routes"]), 1)
        self.assertEqual(len(first_bundle["timetable_rows"]), 1)
        self.assertEqual(len(first_bundle["stop_timetables"]), 1)
        self.assertEqual(first_bundle["timetable_rows"][0]["origin"], "Stop A")
        self.assertEqual(first_bundle["timetable_rows"][0]["destination"], "Stop B")

        snapshot_key = first_bundle["snapshot"]["snapshotKey"]
        summaries = transit_catalog.list_route_payload_summaries(snapshot_key)
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["route_code"], "東98")

        second_bundle = transit_catalog.get_or_refresh_odpt_snapshot(
            operator=DEFAULT_OPERATOR,
            dump=False,
            force_refresh=False,
        )
        self.assertEqual(second_bundle["meta"]["snapshotMode"], "catalog")
        route_payload = transit_catalog.get_route_payload(
            snapshot_key,
            "odpt.Busroute:TokyuBus.T98",
        )
        self.assertIsNotNone(route_payload)
        self.assertEqual(route_payload["trip_count"], 1)

    def test_gtfs_snapshot_round_trips_through_catalog(self) -> None:
        feed_dir = self.tmp_path / "mini_gtfs"
        self._write_minimal_gtfs_feed(feed_dir)

        first_bundle = transit_catalog.get_or_refresh_gtfs_snapshot(feed_path=feed_dir)
        self.assertEqual(first_bundle["meta"]["snapshotMode"], "refreshed")
        self.assertEqual(len(first_bundle["stops"]), 2)
        self.assertEqual(len(first_bundle["routes"]), 1)
        self.assertEqual(len(first_bundle["timetable_rows"]), 1)
        self.assertEqual(len(first_bundle["stop_timetables"]), 2)

        snapshot_key = first_bundle["snapshot"]["snapshotKey"]
        summaries = transit_catalog.list_route_payload_summaries(snapshot_key)
        self.assertEqual(len(summaries), 1)
        route_payload = transit_catalog.get_route_payload(snapshot_key, summaries[0]["route_id"])
        self.assertIsNotNone(route_payload)
        self.assertEqual(route_payload["trip_count"], 1)
        self.assertEqual(route_payload["trips"][0]["origin_stop_name"], "Alpha Stop")
        self.assertEqual(route_payload["trips"][0]["destination_stop_name"], "Beta Stop")

        second_bundle = transit_catalog.get_or_refresh_gtfs_snapshot(feed_path=feed_dir)
        self.assertEqual(second_bundle["meta"]["snapshotMode"], "catalog")

    def _sample_odpt_operational(self) -> dict:
        return {
            "meta": {
                "generatedAt": "2026-03-07T00:00:00+00:00",
                "warnings": [],
                "cache": {
                    "stops": True,
                    "patterns": True,
                    "stopTimetables": True,
                    "timetables": True,
                    "timetableChunks": 1,
                },
            },
            "stops": {
                "odpt.BusstopPole:StopA": {
                    "stop_id": "odpt.BusstopPole:StopA",
                    "name": "Stop A",
                    "lat": 35.0,
                    "lon": 139.0,
                    "poleNumber": "A1",
                },
                "odpt.BusstopPole:StopB": {
                    "stop_id": "odpt.BusstopPole:StopB",
                    "name": "Stop B",
                    "lat": 35.1,
                    "lon": 139.1,
                    "poleNumber": "B1",
                },
            },
            "routePatterns": {
                "odpt.BusroutePattern:T98.Out": {
                    "pattern_id": "odpt.BusroutePattern:T98.Out",
                    "title": "東98",
                    "busroute": "odpt.Busroute:TokyuBus.T98",
                    "stop_sequence": [
                        "odpt.BusstopPole:StopA",
                        "odpt.BusstopPole:StopB",
                    ],
                    "segments": [
                        {
                            "from_stop_id": "odpt.BusstopPole:StopA",
                            "to_stop_id": "odpt.BusstopPole:StopB",
                            "distance_km": 5.2,
                        }
                    ],
                    "total_distance_km": 5.2,
                    "distance_coverage_ratio": 1.0,
                }
            },
            "trips": {
                "odpt.BusTimetable:T98.Weekday.001": {
                    "trip_id": "odpt.BusTimetable:T98.Weekday.001",
                    "pattern_id": "odpt.BusroutePattern:T98.Out",
                    "calendar": "odpt.Calendar:Weekday",
                    "service_id": "weekday",
                    "stop_times": [
                        {
                            "index": 0,
                            "stop_id": "odpt.BusstopPole:StopA",
                            "departure": "06:00",
                        },
                        {
                            "index": 1,
                            "stop_id": "odpt.BusstopPole:StopB",
                            "arrival": "06:25",
                        },
                    ],
                    "estimated_distance_km": 5.2,
                    "distance_source": "pattern_segments",
                    "is_partial": False,
                }
            },
            "stopTimetables": {
                "odpt.BusstopPoleTimetable:StopA:weekday": {
                    "stop_id": "odpt.BusstopPole:StopA",
                    "calendar": "odpt.Calendar:Weekday",
                    "service_id": "weekday",
                    "items": [
                        {
                            "index": 0,
                            "departure": "06:00",
                            "busroutePattern": "odpt.BusroutePattern:T98.Out",
                            "busTimetable": "odpt.BusTimetable:T98.Weekday.001",
                        }
                    ],
                }
            },
            "indexes": {
                "tripsByService": {
                    "weekday": ["odpt.BusTimetable:T98.Weekday.001"],
                    "saturday": [],
                    "holiday": [],
                    "unknown": [],
                },
                "tripsByPattern": {
                    "odpt.BusroutePattern:T98.Out": ["odpt.BusTimetable:T98.Weekday.001"]
                },
            },
            "routeTimetables": [
                {
                    "busroute_id": "odpt.Busroute:TokyuBus.T98",
                    "route_code": "東98",
                    "route_label": "Stop A -> Stop B",
                    "trip_count": 1,
                    "first_departure": "06:00",
                    "last_arrival": "06:25",
                    "patterns": [
                        {
                            "pattern_id": "odpt.BusroutePattern:T98.Out",
                            "title": "東98",
                            "direction": "outbound",
                            "stop_sequence": [
                                {
                                    "stop_id": "odpt.BusstopPole:StopA",
                                    "stop_name": "Stop A",
                                },
                                {
                                    "stop_id": "odpt.BusstopPole:StopB",
                                    "stop_name": "Stop B",
                                },
                            ],
                        }
                    ],
                    "services": [
                        {
                            "service_id": "weekday",
                            "trip_count": 1,
                            "first_departure": "06:00",
                            "last_arrival": "06:25",
                        }
                    ],
                    "trips": [
                        {
                            "trip_id": "odpt.BusTimetable:T98.Weekday.001",
                            "pattern_id": "odpt.BusroutePattern:T98.Out",
                            "service_id": "weekday",
                            "direction": "outbound",
                            "origin_stop_id": "odpt.BusstopPole:StopA",
                            "origin_stop_name": "Stop A",
                            "destination_stop_id": "odpt.BusstopPole:StopB",
                            "destination_stop_name": "Stop B",
                            "departure": "06:00",
                            "arrival": "06:25",
                            "estimated_distance_km": 5.2,
                            "is_partial": False,
                            "stop_times": [
                                {
                                    "index": 0,
                                    "stop_id": "odpt.BusstopPole:StopA",
                                    "stop_name": "Stop A",
                                    "departure": "06:00",
                                    "time": "06:00",
                                },
                                {
                                    "index": 1,
                                    "stop_id": "odpt.BusstopPole:StopB",
                                    "stop_name": "Stop B",
                                    "arrival": "06:25",
                                    "time": "06:25",
                                },
                            ],
                        }
                    ],
                }
            ],
        }

    def _write_minimal_gtfs_feed(self, feed_dir: Path) -> None:
        feed_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "agency.txt": "\n".join(
                [
                    "agency_id,agency_name,agency_url,agency_timezone",
                    "toei,Toei Bus,https://example.com,Asia/Tokyo",
                ]
            ),
            "routes.txt": "\n".join(
                [
                    "route_id,agency_id,route_short_name,route_long_name,route_type,route_color",
                    "R1,toei,東98,Test Route,3,0055aa",
                ]
            ),
            "stops.txt": "\n".join(
                [
                    "stop_id,stop_name,stop_lat,stop_lon",
                    "S1,Alpha Stop,35.0000,139.0000",
                    "S2,Beta Stop,35.1000,139.1000",
                ]
            ),
            "trips.txt": "\n".join(
                [
                    "route_id,service_id,trip_id,direction_id,trip_headsign",
                    "R1,WK,T1,0,Beta Stop",
                ]
            ),
            "stop_times.txt": "\n".join(
                [
                    "trip_id,arrival_time,departure_time,stop_id,stop_sequence",
                    "T1,06:00:00,06:00:00,S1,1",
                    "T1,06:25:00,06:25:00,S2,2",
                ]
            ),
            "calendar.txt": "\n".join(
                [
                    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date",
                    "WK,1,1,1,1,1,0,0,20260101,20261231",
                ]
            ),
        }
        for name, content in files.items():
            (feed_dir / name).write_text(f"{content}\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
