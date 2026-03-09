from __future__ import annotations

import json
from pathlib import Path

from src.gtfs_runtime.loader import load_tokyubus_snapshot_bundle
from src.gtfs_runtime.snapshot_registry import (
    get_latest_tokyubus_snapshot_id,
    list_tokyubus_snapshots,
)
from src.tokyubus_gtfs.archive import archive_raw_snapshot
from src.tokyubus_gtfs.canonical import build_canonical
from src.tokyubus_gtfs.features.charging_windows import build_charging_windows
from src.tokyubus_gtfs.features.deadhead_candidates import build_deadhead_candidates
from src.tokyubus_gtfs.features.depot import build_depot_candidates
from src.tokyubus_gtfs.features.energy import build_energy_features
from src.tokyubus_gtfs.features.stop_distances import build_stop_distance_matrix
from src.tokyubus_gtfs.features.trip_chains import build_trip_chains


def _write_json(path: Path, payload: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _build_fixture(source_dir: Path) -> None:
    _write_json(
        source_dir / "BusstopPole.json",
        [
            {
                "owl:sameAs": "odpt.BusstopPole:StopA",
                "dc:title": "Stop A",
                "geo:lat": 35.0,
                "geo:long": 139.0,
                "odpt:busstopPoleNumber": "1",
            },
            {
                "owl:sameAs": "odpt.BusstopPole:StopB",
                "dc:title": "Stop B営業所",
                "geo:lat": 35.01,
                "geo:long": 139.01,
                "odpt:busstopPoleNumber": "2",
            },
        ],
    )
    _write_json(
        source_dir / "BusroutePattern.json",
        [
            {
                "owl:sameAs": "odpt.BusroutePattern:TokyuBus.A01.out",
                "dc:title": "園０１",
                "odpt:busroute": "odpt.Busroute:TokyuBus.A01",
                "odpt:busstopPoleOrder": [
                    {
                        "odpt:index": 0,
                        "odpt:busstopPole": "odpt.BusstopPole:StopA",
                        "odpt:distance": 0,
                    },
                    {
                        "odpt:index": 1,
                        "odpt:busstopPole": "odpt.BusstopPole:StopB",
                        "odpt:distance": 1000,
                    },
                ],
            }
        ],
    )
    _write_json(
        source_dir / "BusTimetable.json",
        [
            {
                "owl:sameAs": "odpt.BusTimetable:TokyuBus.A01.weekday.0600",
                "odpt:calendar": "odpt.Calendar:Weekday",
                "odpt:busroutePattern": "odpt.BusroutePattern:TokyuBus.A01.out",
                "odpt:busTimetableObject": [
                    {
                        "odpt:index": 0,
                        "odpt:busstopPole": "odpt.BusstopPole:StopA",
                        "odpt:departureTime": "06:00",
                    },
                    {
                        "odpt:index": 1,
                        "odpt:busstopPole": "odpt.BusstopPole:StopB",
                        "odpt:arrivalTime": "06:20",
                    },
                ],
            },
            {
                "owl:sameAs": "odpt.BusTimetable:TokyuBus.A01.weekday.0645",
                "odpt:calendar": "odpt.Calendar:Weekday",
                "odpt:busroutePattern": "odpt.BusroutePattern:TokyuBus.A01.out",
                "odpt:busTimetableObject": [
                    {
                        "odpt:index": 0,
                        "odpt:busstopPole": "odpt.BusstopPole:StopB",
                        "odpt:departureTime": "06:45",
                    },
                    {
                        "odpt:index": 1,
                        "odpt:busstopPole": "odpt.BusstopPole:StopA",
                        "odpt:arrivalTime": "07:00",
                    },
                ],
            },
        ],
    )
    _write_json(
        source_dir / "BusstopPoleTimetable.json",
        [
            {
                "owl:sameAs": "odpt.BusstopPoleTimetable:StopA:weekday",
                "odpt:busstopPole": "odpt.BusstopPole:StopA",
                "odpt:calendar": "odpt.Calendar:Weekday",
                "odpt:busstopPoleTimetableObject": [
                    {
                        "odpt:departureTime": "06:00",
                        "odpt:busroutePattern": "odpt.BusroutePattern:TokyuBus.A01.out",
                        "odpt:busroute": "odpt.Busroute:TokyuBus.A01",
                    }
                ],
            }
        ],
    )


def test_load_tokyubus_runtime_bundle(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw_input"
    archive_root = tmp_path / "archive"
    canonical_root = tmp_path / "canonical"
    features_root = tmp_path / "features"
    _build_fixture(source_dir)

    archive_raw_snapshot(
        source_dir, snapshot_id="snap-rt-001", archive_root=archive_root
    )
    build_canonical(
        archive_root / "snap-rt-001", out_dir=canonical_root / "snap-rt-001"
    )

    feature_dir = features_root / "snap-rt-001"
    build_trip_chains(canonical_root / "snap-rt-001", feature_dir)
    build_energy_features(canonical_root / "snap-rt-001", feature_dir)
    build_depot_candidates(canonical_root / "snap-rt-001", feature_dir)
    build_stop_distance_matrix(canonical_root / "snap-rt-001", feature_dir)
    build_charging_windows(canonical_root / "snap-rt-001", feature_dir)
    build_deadhead_candidates(canonical_root / "snap-rt-001", feature_dir)

    snapshots = list_tokyubus_snapshots(
        canonical_root=canonical_root, features_root=features_root
    )
    assert snapshots[0]["snapshot_id"] == "snap-rt-001"
    assert (
        get_latest_tokyubus_snapshot_id(
            canonical_root=canonical_root, features_root=features_root
        )
        == "snap-rt-001"
    )

    bundle = load_tokyubus_snapshot_bundle(
        snapshot_id="snap-rt-001",
        canonical_root=canonical_root,
        features_root=features_root,
    )
    assert bundle["meta"]["snapshotId"] == "snap-rt-001"
    assert bundle["meta"]["feed_id"] == "tokyu_odpt_gtfs"
    assert bundle["meta"]["dataset_id"] == "tokyu_odpt_gtfs:snap-rt-001"
    assert bundle["routes"][0]["scopedRouteId"].startswith("tokyu_odpt_gtfs:")
    assert len(bundle["stops"]) == 2
    assert len(bundle["routes"]) == 1
    assert len(bundle["timetable_rows"]) == 2
    assert len(bundle["features"]["deadhead_candidates"]) == 2
