import hashlib
import json
import pathlib
import tempfile

import pandas as pd
import pytest

from src.artifact_contract import (
    ArtifactContractError,
    ContractErrorCode,
    RUNTIME_VERSION,
    check_artifact_contract,
)
from src.dataset_integrity import DatasetIntegrityError, check_dataset_integrity


VALID_MANIFEST = {
    "dataset_id": "tokyu_core",
    "dataset_version": "2026-03-13",
    "generated_at": "2026-03-13T00:00:00Z",
    "source": "test fixture",
    "schema_version": "v1",
    "producer_version": "0.1.0",
    "min_runtime_version": "0.1.0",
    "included_depots": ["meguro"],
    "included_routes": ["route-01", "route-02"],
    "seed_hash": "abc123",
    "artifact_hashes": {},
    "row_counts": {"routes": 1, "trips": 1, "timetables": 1},
    "schema_versions": {"routes": "v1", "trips": "v1", "timetables": "v1"},
}

MINIMAL_ROUTES = pd.DataFrame(
    [
        {
            "id": "tokyu:route-01",
            "routeCode": "route-01",
            "routeLabel": "route-01",
            "name": "route-01",
        }
    ]
)
MINIMAL_TRIPS = pd.DataFrame(
    [
        {
            "trip_id": "t001",
            "route_id": "tokyu:route-01",
            "service_id": "weekday",
            "departure": "06:00:00",
            "arrival": "07:00:00",
        }
    ]
)
MINIMAL_TIMETABLES = pd.DataFrame(
    [
        {
            "trip_id": "t001",
            "route_id": "tokyu:route-01",
            "service_id": "weekday",
            "origin": "A",
            "destination": "B",
            "departure": "06:00:00",
            "arrival": "07:00:00",
        }
    ]
)


def make_built_dir(tmp: pathlib.Path, manifest_override: dict | None = None) -> pathlib.Path:
    built_dir = tmp / "tokyu_core"
    built_dir.mkdir()
    MINIMAL_ROUTES.to_parquet(built_dir / "routes.parquet")
    MINIMAL_TRIPS.to_parquet(built_dir / "trips.parquet")
    MINIMAL_TIMETABLES.to_parquet(built_dir / "timetables.parquet")

    manifest = dict(VALID_MANIFEST)
    manifest["artifact_hashes"] = {
        name: hashlib.sha256((built_dir / name).read_bytes()).hexdigest()
        for name in ["routes.parquet", "trips.parquet", "timetables.parquet"]
    }
    if manifest_override:
        manifest.update(manifest_override)
    (built_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return built_dir


def test_valid_built_dir_passes_contract():
    with tempfile.TemporaryDirectory() as tmp:
        built_dir = make_built_dir(pathlib.Path(tmp))
        result = check_artifact_contract(built_dir, verify_hashes=True)
        assert result["dataset_id"] == "tokyu_core"


def test_missing_manifest_raises_manifest_missing():
    with tempfile.TemporaryDirectory() as tmp:
        built_dir = pathlib.Path(tmp) / "tokyu_core"
        built_dir.mkdir()
        MINIMAL_ROUTES.to_parquet(built_dir / "routes.parquet")
        MINIMAL_TRIPS.to_parquet(built_dir / "trips.parquet")
        MINIMAL_TIMETABLES.to_parquet(built_dir / "timetables.parquet")
        with pytest.raises(ArtifactContractError) as exc:
            check_artifact_contract(built_dir, verify_hashes=False)
        assert exc.value.code == ContractErrorCode.MANIFEST_MISSING


def test_missing_parquet_raises_artifact_missing():
    with tempfile.TemporaryDirectory() as tmp:
        built_dir = make_built_dir(pathlib.Path(tmp))
        (built_dir / "trips.parquet").unlink()
        with pytest.raises(ArtifactContractError) as exc:
            check_artifact_contract(built_dir, verify_hashes=False)
        assert exc.value.code == ContractErrorCode.ARTIFACT_MISSING


def test_corrupted_parquet_raises_hash_mismatch():
    with tempfile.TemporaryDirectory() as tmp:
        built_dir = make_built_dir(pathlib.Path(tmp))
        (built_dir / "routes.parquet").write_bytes(b"corrupted")
        with pytest.raises(ArtifactContractError) as exc:
            check_artifact_contract(built_dir, verify_hashes=True)
        assert exc.value.code == ContractErrorCode.ARTIFACT_HASH_MISMATCH


def test_runtime_version_too_old_raises_error():
    with tempfile.TemporaryDirectory() as tmp:
        built_dir = make_built_dir(
            pathlib.Path(tmp),
            manifest_override={"min_runtime_version": "99.0.0"},
        )
        with pytest.raises(ArtifactContractError) as exc:
            check_artifact_contract(built_dir, verify_hashes=False)
        assert exc.value.code == ContractErrorCode.RUNTIME_VERSION_TOO_OLD


def test_unsupported_manifest_schema_version_raises_error():
    with tempfile.TemporaryDirectory() as tmp:
        built_dir = make_built_dir(
            pathlib.Path(tmp),
            manifest_override={"schema_version": "v999"},
        )
        with pytest.raises(ArtifactContractError) as exc:
            check_artifact_contract(built_dir, verify_hashes=False)
        assert exc.value.code == ContractErrorCode.SCHEMA_VERSION_UNSUPPORTED


def test_invalid_manifest_json_raises_manifest_invalid():
    with tempfile.TemporaryDirectory() as tmp:
        built_dir = make_built_dir(pathlib.Path(tmp))
        (built_dir / "manifest.json").write_text("not valid json {{{", encoding="utf-8")
        with pytest.raises(ArtifactContractError) as exc:
            check_artifact_contract(built_dir, verify_hashes=False)
        assert exc.value.code == ContractErrorCode.MANIFEST_INVALID
