from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.fast_catalog_ingest import build_bundle_artifacts


def _write_json(path: Path, payload: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class FastCatalogIngestTest(unittest.TestCase):
    def test_build_bundle_artifacts_from_raw_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            raw_dir = base / "raw"
            _write_json(
                raw_dir / "busstop_pole.json",
                [
                    {
                        "@id": "odpt.BusstopPole:StopA",
                        "owl:sameAs": "odpt.BusstopPole:StopA",
                        "dc:title": "Stop A",
                        "geo:lat": 35.0,
                        "geo:long": 139.0,
                    },
                    {
                        "@id": "odpt.BusstopPole:StopB",
                        "owl:sameAs": "odpt.BusstopPole:StopB",
                        "dc:title": "Stop B",
                        "geo:lat": 35.1,
                        "geo:long": 139.1,
                    },
                ],
            )
            _write_json(
                raw_dir / "busroute_pattern.json",
                [
                    {
                        "@id": "odpt.BusroutePattern:T98.Out",
                        "owl:sameAs": "odpt.BusroutePattern:T98.Out",
                        "dc:title": "東98",
                        "odpt:busroute": "odpt.Busroute:TokyuBus.T98",
                        "odpt:busstopPoleOrder": [
                            {"odpt:index": 0, "odpt:busstopPole": "odpt.BusstopPole:StopA", "odpt:distance": 0},
                            {"odpt:index": 1, "odpt:busstopPole": "odpt.BusstopPole:StopB", "odpt:distance": 5200},
                        ],
                    }
                ],
            )
            _write_json(
                raw_dir / "bus_timetable.json",
                [
                    {
                        "@id": "odpt.BusTimetable:T98.Weekday.001",
                        "owl:sameAs": "odpt.BusTimetable:T98.Weekday.001",
                        "odpt:busroutePattern": "odpt.BusroutePattern:T98.Out",
                        "odpt:calendar": "odpt.Calendar:Weekday",
                        "odpt:busTimetableObject": [
                            {
                                "odpt:index": 0,
                                "odpt:busstopPole": "odpt.BusstopPole:StopA",
                                "odpt:departureTime": "06:00",
                            },
                            {
                                "odpt:index": 1,
                                "odpt:busstopPole": "odpt.BusstopPole:StopB",
                                "odpt:arrivalTime": "06:25",
                            },
                        ],
                    }
                ],
            )
            _write_json(
                raw_dir / "busstop_pole_timetable.json",
                [
                    {
                        "@id": "odpt.BusstopPoleTimetable:StopA:weekday",
                        "owl:sameAs": "odpt.BusstopPoleTimetable:StopA:weekday",
                        "odpt:busstopPole": "odpt.BusstopPole:StopA",
                        "odpt:calendar": "odpt.Calendar:Weekday",
                        "odpt:busstopPoleTimetableObject": [
                            {
                                "odpt:departureTime": "06:00",
                                "odpt:busroutePattern": "odpt.BusroutePattern:T98.Out",
                                "odpt:busroute": "odpt.Busroute:TokyuBus.T98",
                            }
                        ],
                    }
                ],
            )

            bundle = build_bundle_artifacts(base, "odpt.Operator:TokyuBus")
            self.assertEqual(len(bundle["routes"]), 1)
            self.assertEqual(len(bundle["stops"]), 2)
            self.assertEqual(len(bundle["timetable_rows"]), 1)
            self.assertEqual(len(bundle["stop_timetables"]), 1)
            self.assertEqual(len(bundle["route_payloads"]), 1)
            operational = json.loads((base / "operational_dataset.json").read_text(encoding="utf-8"))
            self.assertEqual(len(operational["routeTimetables"]), 1)
            self.assertIn("odpt.BusTimetable:T98.Weekday.001", operational["trips"])
