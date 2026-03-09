from __future__ import annotations

import json
from pathlib import Path

from src.tokyubus_gtfs.archive import archive_raw_snapshot
from src.tokyubus_gtfs.canonical import build_canonical
from src.tokyubus_gtfs.features.charging_windows import build_charging_windows
from src.tokyubus_gtfs.features.deadhead_candidates import build_deadhead_candidates
from src.tokyubus_gtfs.features.depot import build_depot_candidates
from src.tokyubus_gtfs.features.energy import build_energy_features
from src.tokyubus_gtfs.features.stop_distances import build_stop_distance_matrix
from src.tokyubus_gtfs.features.trip_chains import build_trip_chains
from src.tokyubus_gtfs.gtfs_export import export_gtfs
from src.tokyubus_gtfs.pipeline import PipelineConfig, run_pipeline
from src.tokyubus_gtfs.validate import validate_gtfs_feed


def _write_json(path: Path, payload: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, payload: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in payload:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


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
                    {"odpt:index": 0, "odpt:busstopPole": "odpt.BusstopPole:StopA", "odpt:distance": 0},
                    {"odpt:index": 1, "odpt:busstopPole": "odpt.BusstopPole:StopB", "odpt:distance": 1000},
                ],
            },
            {
                "owl:sameAs": "odpt.BusroutePattern:TokyuBus.A01.in",
                "dc:title": "園０１",
                "odpt:busroute": "odpt.Busroute:TokyuBus.A01",
                "odpt:busstopPoleOrder": [
                    {"odpt:index": 0, "odpt:busstopPole": "odpt.BusstopPole:StopB", "odpt:distance": 0},
                    {"odpt:index": 1, "odpt:busstopPole": "odpt.BusstopPole:StopA", "odpt:distance": 1000},
                ],
            },
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
                "odpt:busroutePattern": "odpt.BusroutePattern:TokyuBus.A01.in",
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


def _build_fixture_with_stop_timetable_change(source_dir: Path) -> None:
    _build_fixture(source_dir)
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
                    },
                    {
                        "odpt:departureTime": "06:45",
                        "odpt:busroutePattern": "odpt.BusroutePattern:TokyuBus.A01.out",
                        "odpt:busroute": "odpt.Busroute:TokyuBus.A01",
                    },
                ],
            }
        ],
    )


def test_layered_pipeline_outputs(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw_input"
    archive_root = tmp_path / "archive"
    canonical_root = tmp_path / "canonical"
    gtfs_root = tmp_path / "gtfs"
    features_root = tmp_path / "features"
    _build_fixture(source_dir)

    manifest = archive_raw_snapshot(
        source_dir,
        snapshot_id="snap-001",
        archive_root=archive_root,
    )
    assert manifest["snapshot_id"] == "snap-001"
    assert (archive_root / "snap-001" / "manifest.json").exists()

    summary = build_canonical(
        archive_root / "snap-001",
        out_dir=canonical_root / "snap-001",
    )
    assert summary.entity_counts["operators"] == 1
    assert summary.entity_counts["routes"] == 1
    assert summary.entity_counts["route_patterns"] == 2
    assert summary.entity_counts["stop_poles"] == 2
    assert summary.entity_counts["shapes"] == 4
    assert (canonical_root / "snap-001" / "source_lineage.jsonl").exists()
    assert (canonical_root / "snap-001" / "route_patterns.jsonl").exists()

    gtfs_result = export_gtfs(canonical_root / "snap-001", out_dir=gtfs_root)
    assert gtfs_result["routes"] == 1
    assert gtfs_result["trips"] == 2
    assert gtfs_result["sidecars"]["trip_odpt_extra"] == 2
    assert gtfs_result["sidecars"]["route_patterns"] == 2
    assert (gtfs_root / "sidecar_snapshot_manifest.json").exists()
    assert (gtfs_root / "shapes.txt").exists()
    assert (gtfs_root / "feed_metadata.json").exists()

    validation = validate_gtfs_feed(canonical_root / "snap-001", gtfs_dir=gtfs_root)
    assert validation["valid"] is True
    assert validation["feed_id"] == "tokyu_odpt_gtfs"
    assert (gtfs_root / "validation_report.json").exists()

    chains = build_trip_chains(canonical_root / "snap-001", features_root)
    energy = build_energy_features(canonical_root / "snap-001", features_root)
    depot = build_depot_candidates(canonical_root / "snap-001", features_root)
    distances = build_stop_distance_matrix(canonical_root / "snap-001", features_root)
    deadhead = build_deadhead_candidates(canonical_root / "snap-001", features_root)
    charging = build_charging_windows(canonical_root / "snap-001", features_root)

    assert chains["chain_count"] >= 1
    assert energy["estimate_count"] == 2
    assert depot["candidate_count"] == 1
    assert distances["pair_count"] == 1
    assert deadhead["candidate_count"] == 2
    assert charging["window_count"] >= 1


def test_gtfs_export_excludes_deadhead_and_non_public_patterns(tmp_path: Path) -> None:
    canonical_dir = tmp_path / "canonical"
    gtfs_dir = tmp_path / "gtfs"

    _write_jsonl(
        canonical_dir / "routes.jsonl",
        [
            {
                "route_id": "tokyu:a01_family",
                "route_code": "園０１",
                "route_name": "園０１",
                "route_type": 3,
                "route_color": "#123456",
            }
        ],
    )
    _write_jsonl(
        canonical_dir / "route_patterns.jsonl",
        [
            {
                "pattern_id": "route-a01-main",
                "route_id": "tokyu:a01_family",
                "include_in_public_gtfs": True,
            },
            {
                "pattern_id": "route-a01-deadhead",
                "route_id": "tokyu:a01_family",
                "include_in_public_gtfs": False,
            },
        ],
    )
    _write_jsonl(
        canonical_dir / "trips.jsonl",
        [
            {
                "trip_id": "trip-public",
                "route_id": "tokyu:a01_family",
                "pattern_id": "route-a01-main",
                "service_id": "WEEKDAY",
                "direction_id": 0,
                "direction": "outbound",
                "destination_name": "Stop B",
                "shape_id": "shape_route-a01-main",
                "trip_role": "service",
                "is_public_trip": True,
            },
            {
                "trip_id": "trip-deadhead",
                "route_id": "tokyu:a01_family",
                "pattern_id": "route-a01-deadhead",
                "service_id": "WEEKDAY",
                "direction_id": 1,
                "direction": "inbound",
                "destination_name": "Stop A",
                "shape_id": "shape_route-a01-deadhead",
                "trip_role": "deadhead",
                "is_public_trip": True,
            },
        ],
    )
    _write_jsonl(
        canonical_dir / "stop_times.jsonl",
        [
            {
                "trip_id": "trip-public",
                "arrival_time": "06:00:00",
                "departure_time": "06:00:00",
                "stop_id": "stop-a",
                "stop_sequence": 0,
            },
            {
                "trip_id": "trip-deadhead",
                "arrival_time": "06:10:00",
                "departure_time": "06:10:00",
                "stop_id": "stop-b",
                "stop_sequence": 0,
            },
        ],
    )
    _write_jsonl(
        canonical_dir / "stops.jsonl",
        [
            {"stop_id": "stop-a", "stop_name": "Stop A", "lat": 35.0, "lon": 139.0},
            {"stop_id": "stop-b", "stop_name": "Stop B", "lat": 35.1, "lon": 139.1},
        ],
    )
    _write_jsonl(
        canonical_dir / "services.jsonl",
        [
            {
                "service_id": "WEEKDAY",
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": False,
                "sunday": False,
                "start_date": "2025-04-01",
                "end_date": "2026-03-31",
            }
        ],
    )
    _write_jsonl(
        canonical_dir / "shapes.jsonl",
        [
            {
                "shape_id": "shape_route-a01-main",
                "shape_pt_lat": 35.0,
                "shape_pt_lon": 139.0,
                "shape_pt_sequence": 0,
                "shape_dist_traveled_km": 0.0,
            },
            {
                "shape_id": "shape_route-a01-deadhead",
                "shape_pt_lat": 35.1,
                "shape_pt_lon": 139.1,
                "shape_pt_sequence": 0,
                "shape_dist_traveled_km": 0.0,
            },
        ],
    )
    (canonical_dir / "canonical_summary.json").write_text(
        json.dumps(
            {
                "snapshot_id": "snap-001",
                "entity_counts": {"routes": 1, "trips": 2, "stop_times": 2, "services": 1},
            }
        ),
        encoding="utf-8",
    )

    result = export_gtfs(canonical_dir, out_dir=gtfs_dir)

    assert result["routes"] == 1
    assert result["trips"] == 1
    assert result["stop_times"] == 1
    assert result["shapes"] == 1


def test_pipeline_reuses_downstream_outputs_when_only_stop_timetable_changes(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    archive_root = tmp_path / "archive"
    canonical_root = tmp_path / "canonical"
    gtfs_root = tmp_path / "gtfs"
    features_root = tmp_path / "features"

    source_a = raw_root / "a"
    source_b = raw_root / "b"
    _build_fixture(source_a)
    _build_fixture_with_stop_timetable_change(source_b)

    first = run_pipeline(
        PipelineConfig(
            source_dir=source_a,
            snapshot_id="20260309T010000Z",
            archive_root=archive_root,
            canonical_root=canonical_root,
            gtfs_out_dir=gtfs_root,
            features_root=features_root,
        )
    )
    second = run_pipeline(
        PipelineConfig(
            source_dir=source_b,
            snapshot_id="20260309T020000Z",
            archive_root=archive_root,
            canonical_root=canonical_root,
            gtfs_out_dir=gtfs_root,
            features_root=features_root,
        )
    )

    assert first["features"]["skipped"] is False
    assert second["resource_diff"]["changed_resources"] == ["odpt:BusstopPoleTimetable"]
    assert second["canonical"]["rebuilt_tables"] == ["stop_timetables"]
    assert "routes" in second["canonical"]["reused_tables"]
    assert "trips" in second["canonical"]["reused_tables"]
    assert second["gtfs"]["skipped"] is True
    assert second["features"]["skipped"] is True
    assert second["features"]["reused_from_snapshot"] == "20260309T010000Z"
    assert (features_root / "20260309T020000Z" / "trip_chains.json").exists()


def test_pipeline_fast_profile_skips_heavy_features(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw_input"
    archive_root = tmp_path / "archive"
    canonical_root = tmp_path / "canonical"
    gtfs_root = tmp_path / "gtfs"
    features_root = tmp_path / "features"
    _build_fixture(source_dir)

    result = run_pipeline(
        PipelineConfig(
            source_dir=source_dir,
            snapshot_id="20260309T030000Z",
            archive_root=archive_root,
            canonical_root=canonical_root,
            gtfs_out_dir=gtfs_root,
            features_root=features_root,
            profile="fast",
        )
    )

    assert result["features"]["skipped"] is True
    assert result["features"]["reason"] == "profile=fast"
