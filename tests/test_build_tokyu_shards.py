from __future__ import annotations

import csv
import json
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _fixture_roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    seed_root = tmp_path / "seed" / "tokyu"
    canonical_root = tmp_path / "canonical"
    output_root = tmp_path / "outputs" / "built" / "tokyu"

    _write_json(
        seed_root / "depots.json",
        {
            "operator_id": "tokyu",
            "depots": [
                {
                    "id": "meguro",
                    "depotId": "meguro",
                    "name": "目黒営業所",
                    "lat": 35.0,
                    "lon": 139.0,
                    "notes": "",
                }
            ],
        },
    )
    _write_json(
        seed_root / "version.json",
        {
            "seed_version": "seed-test",
            "dataset_version": "2026-03-14",
        },
    )
    _write_json(
        seed_root / "datasets" / "toy.json",
        {
            "dataset_id": "toy",
            "included_depots": ["meguro"],
            "included_routes": "ALL",
        },
    )
    _write_csv(
        seed_root / "route_to_depot.csv",
        [
            {
                "route_code": "黒01",
                "depot_id": "meguro",
                "depot_name": "目黒営業所",
                "region": "東京",
                "route_map_as_of": "2026-03-14",
                "notes": "",
            }
        ],
    )

    snapshot_root = canonical_root / "20260314T000000Z"
    _write_jsonl(
        snapshot_root / "routes.jsonl",
        [
            {
                "route_id": "tokyu:kuro01_family",
                "route_family_code": "黒01",
                "route_name": "黒01",
                "origin_stop_id": "STOP_A",
                "destination_stop_id": "STOP_B",
                "origin_name": "A",
                "destination_name": "B",
            }
        ],
    )
    _write_jsonl(
        snapshot_root / "route_patterns.jsonl",
        [
            {
                "pattern_id": "pattern-main-out",
                "route_id": "tokyu:kuro01_family",
                "pattern_role": "main",
                "direction_bucket": 0,
                "first_stop_id": "STOP_A",
                "last_stop_id": "STOP_B",
                "first_stop_name": "A",
                "last_stop_name": "B",
                "route_short_name_hint": "黒01",
                "route_long_name_hint": "黒01 (A -> B)",
                "distance_km": 5.0,
            },
            {
                "pattern_id": "pattern-depot-in",
                "route_id": "tokyu:kuro01_family",
                "pattern_role": "depot_in",
                "direction_bucket": 1,
                "first_stop_id": "STOP_B",
                "last_stop_id": "STOP_A",
                "first_stop_name": "B",
                "last_stop_name": "A",
                "route_short_name_hint": "黒01",
                "route_long_name_hint": "黒01 (B -> A)",
                "distance_km": 5.0,
            },
        ],
    )
    _write_jsonl(
        snapshot_root / "services.jsonl",
        [
            {"service_id": "WEEKDAY"},
            {"service_id": "SUN_HOL"},
        ],
    )
    _write_jsonl(
        snapshot_root / "trips.jsonl",
        [
            {
                "trip_id": "trip-weekday",
                "route_id": "tokyu:kuro01_family",
                "pattern_id": "pattern-main-out",
                "service_id": "WEEKDAY",
                "direction": "outbound",
                "trip_index": 0,
                "origin_stop_id": "STOP_A",
                "destination_stop_id": "STOP_B",
                "origin_name": "A",
                "destination_name": "B",
                "departure_time": "06:00:00",
                "arrival_time": "06:20:00",
                "distance_km": 5.0,
                "runtime_min": 20.0,
                "allowed_vehicle_types": ["BEV", "ICE"],
            },
            {
                "trip_id": "trip-holiday",
                "route_id": "tokyu:kuro01_family",
                "pattern_id": "pattern-depot-in",
                "service_id": "SUN_HOL",
                "direction": "inbound",
                "trip_index": 1,
                "origin_stop_id": "STOP_B",
                "destination_stop_id": "STOP_A",
                "origin_name": "B",
                "destination_name": "A",
                "departure_time": "08:00:00",
                "arrival_time": "08:25:00",
                "distance_km": 5.0,
                "runtime_min": 25.0,
                "allowed_vehicle_types": ["ICE"],
            },
        ],
    )
    _write_jsonl(
        snapshot_root / "stop_times.jsonl",
        [
            {
                "trip_id": "trip-weekday",
                "stop_sequence": 0,
                "stop_id": "STOP_A",
                "stop_name": "A",
                "arrival_time": "06:00:00",
                "departure_time": "06:00:00",
            },
            {
                "trip_id": "trip-weekday",
                "stop_sequence": 1,
                "stop_id": "STOP_B",
                "stop_name": "B",
                "arrival_time": "06:20:00",
                "departure_time": "06:20:00",
            },
            {
                "trip_id": "trip-holiday",
                "stop_sequence": 0,
                "stop_id": "STOP_B",
                "stop_name": "B",
                "arrival_time": "08:00:00",
                "departure_time": "08:00:00",
            },
            {
                "trip_id": "trip-holiday",
                "stop_sequence": 1,
                "stop_id": "STOP_A",
                "stop_name": "A",
                "arrival_time": "08:25:00",
                "departure_time": "08:25:00",
            },
        ],
    )
    return seed_root, canonical_root, output_root


def test_build_tokyu_shards_generates_manifest_and_shards(tmp_path: Path):
    from importlib.util import module_from_spec, spec_from_file_location

    source_path = Path(__file__).resolve().parents[1] / "data-prep" / "pipeline" / "build_tokyu_shards.py"
    spec = spec_from_file_location("build_tokyu_shards_test", source_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    seed_root, canonical_root, output_root = _fixture_roots(tmp_path)
    result = module.build_tokyu_shards(
        "toy",
        canonical_root=canonical_root,
        seed_root=seed_root,
        output_root=output_root,
        schema_root=Path(__file__).resolve().parents[1] / "schema" / "tokyu_shards",
    )

    assert result["dataset_id"] == "toy"
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    shard_manifest = json.loads((output_root / "shard_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output_root / "depot_route_summary.json").read_text(encoding="utf-8"))
    trip_weekday = json.loads(
        (output_root / "trip_shards" / "meguro" / "黒01" / "weekday.json").read_text(encoding="utf-8")
    )

    assert manifest["dataset_id"] == "toy"
    assert manifest["available_depots"] == ["meguro"]
    assert manifest["available_routes"] == ["黒01"]
    assert set(manifest["available_day_types"]) == {"weekday", "holiday"}
    assert len(shard_manifest["items"]) == 6
    assert summary["items"][0]["weekday_trip_count"] == 1
    assert summary["items"][0]["holiday_trip_count"] == 1
    assert trip_weekday["items"][0]["trip_id"] == "trip-weekday"
    assert trip_weekday["items"][0]["stop_time_count"] == 2

    validate_result = module.build_tokyu_shards(
        "toy",
        validate_only=True,
        canonical_root=canonical_root,
        seed_root=seed_root,
        output_root=output_root,
        schema_root=Path(__file__).resolve().parents[1] / "schema" / "tokyu_shards",
    )
    assert validate_result["mode"] == "validate_only"


def test_runtime_scope_prefers_tokyu_shards_when_manifest_is_ready(tmp_path: Path, monkeypatch):
    import src.runtime_scope as runtime_scope
    import src.tokyu_shard_loader as shard_loader

    built_dir = tmp_path / "toy"
    built_dir.mkdir(parents=True)
    shard_root = tmp_path / "outputs" / "built" / "tokyu"
    _write_json(
        shard_root / "manifest.json",
        {
            "dataset_id": "toy",
            "operator": "Tokyu",
            "operator_id": "tokyu",
            "build_timestamp": "2026-03-14T00:00:00+00:00",
            "source_version": "20260314T000000Z",
            "shard_version": "1.0.0",
            "available_depots": ["meguro"],
            "available_routes": ["黒01"],
            "available_day_types": ["weekday"],
            "output_files": [],
            "warning_count": 0,
        },
    )
    _write_json(shard_root / "depots.json", {"dataset_id": "toy", "operator_id": "tokyu", "depots": []})
    _write_json(shard_root / "routes.json", {"dataset_id": "toy", "operator_id": "tokyu", "routes": []})
    _write_json(
        shard_root / "depot_route_index.json",
        {
            "dataset_id": "toy",
            "operator_id": "tokyu",
            "depots": [{"depot_id": "meguro", "route_ids": ["黒01"]}],
            "routes": [{"route_id": "黒01", "depot_ids": ["meguro"], "available_day_types": ["weekday"]}],
        },
    )
    _write_json(
        shard_root / "depot_route_summary.json",
        {
            "dataset_id": "toy",
            "operator_id": "tokyu",
            "items": [
                {
                    "depot_id": "meguro",
                    "route_id": "黒01",
                    "weekday_trip_count": 1,
                    "saturday_trip_count": 0,
                    "holiday_trip_count": 0,
                    "first_departure": "06:00:00",
                    "last_departure": "06:00:00",
                    "main_trip_count": 1,
                    "short_turn_trip_count": 0,
                    "depot_in_trip_count": 0,
                    "depot_out_trip_count": 0,
                }
            ],
        },
    )
    _write_json(
        shard_root / "trip_shards" / "meguro" / "黒01" / "weekday.json",
        {
            "dataset_id": "toy",
            "operator_id": "tokyu",
            "source_version": "20260314T000000Z",
            "artifact_kind": "trip_shard",
            "depot_id": "meguro",
            "route_id": "黒01",
            "day_type": "weekday",
            "items": [
                {
                    "trip_id": "trip-1",
                    "depot_id": "meguro",
                    "route_id": "黒01",
                    "day_type": "weekday",
                    "direction": "outbound",
                    "service_variant": "main",
                    "origin_stop_id": "STOP_A",
                    "destination_stop_id": "STOP_B",
                    "origin_name": "A",
                    "destination_name": "B",
                    "departure_time": "06:00:00",
                    "arrival_time": "06:20:00",
                    "block_hint": None,
                    "distance_hint_km": 5.0,
                    "runtime_minutes": 20.0,
                    "allowed_vehicle_types": ["BEV", "ICE"],
                    "trip_index": 0,
                    "stop_time_count": 2,
                }
            ],
        },
    )
    _write_json(
        shard_root / "stop_time_shards" / "meguro" / "黒01" / "weekday.json",
        {
            "dataset_id": "toy",
            "operator_id": "tokyu",
            "source_version": "20260314T000000Z",
            "artifact_kind": "stop_time_shard",
            "depot_id": "meguro",
            "route_id": "黒01",
            "day_type": "weekday",
            "items": [
                {
                    "trip_id": "trip-1",
                    "depot_id": "meguro",
                    "route_id": "黒01",
                    "day_type": "weekday",
                    "direction": "outbound",
                    "service_variant": "main",
                    "origin_stop_id": "STOP_A",
                    "destination_stop_id": "STOP_B",
                    "origin_name": "A",
                    "destination_name": "B",
                    "departure_time": "06:00:00",
                    "arrival_time": "06:20:00",
                    "stop_times": [
                        {
                            "seq": 0,
                            "stop_id": "STOP_A",
                            "stop_name": "A",
                            "arrival_time": "06:00:00",
                            "departure_time": "06:00:00"
                        },
                        {
                            "seq": 1,
                            "stop_id": "STOP_B",
                            "stop_name": "B",
                            "arrival_time": "06:20:00",
                            "departure_time": "06:20:00"
                        }
                    ]
                }
            ]
        },
    )
    _write_json(
        shard_root / "timetable_shards" / "meguro" / "黒01" / "weekday.json",
        {
            "dataset_id": "toy",
            "operator_id": "tokyu",
            "source_version": "20260314T000000Z",
            "artifact_kind": "timetable_shard",
            "depot_id": "meguro",
            "route_id": "黒01",
            "day_type": "weekday",
            "items": []
        },
    )
    _write_json(
        shard_root / "shard_manifest.json",
        {
            "dataset_id": "toy",
            "operator_id": "tokyu",
            "items": [
                {
                    "artifact_kind": "trip_shard",
                    "depot_id": "meguro",
                    "route_id": "黒01",
                    "day_type": "weekday",
                    "trip_count": 1,
                    "stop_time_count": 2,
                    "artifact_path": "trip_shards/meguro/黒01/weekday.json",
                    "hash": "placeholder",
                    "size_bytes": 0
                },
                {
                    "artifact_kind": "stop_time_shard",
                    "depot_id": "meguro",
                    "route_id": "黒01",
                    "day_type": "weekday",
                    "trip_count": 1,
                    "stop_time_count": 2,
                    "artifact_path": "stop_time_shards/meguro/黒01/weekday.json",
                    "hash": "placeholder",
                    "size_bytes": 0
                }
            ]
        },
    )

    # Local test helper: use the builder module's hash function for correctness.
    from importlib.util import module_from_spec, spec_from_file_location

    source_path = Path(__file__).resolve().parents[1] / "data-prep" / "pipeline" / "build_tokyu_shards.py"
    spec = spec_from_file_location("build_tokyu_shards_hash_test", source_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    shard_manifest_payload = json.loads((shard_root / "shard_manifest.json").read_text(encoding="utf-8"))
    for item in shard_manifest_payload["items"]:
        payload_path = shard_root / item["artifact_path"]
        item["hash"] = module._hash_file(payload_path)
        item["size_bytes"] = payload_path.stat().st_size
    (shard_root / "shard_manifest.json").write_text(
        json.dumps(shard_manifest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(shard_loader, "TOKYU_SHARD_ROOT", shard_root)

    scope = runtime_scope.RuntimeScope(
        depot_ids=["meguro"],
        route_ids=["tokyu:meguro:黒01"],
        service_ids=["WEEKDAY"],
    )
    trips_df = runtime_scope.load_scoped_trips(built_dir, scope)
    timetables_df = runtime_scope.load_scoped_timetables(built_dir, scope)

    assert list(trips_df["trip_id"]) == ["trip-1"]
    assert list(timetables_df["stop_id"]) == ["STOP_A", "STOP_B"]
