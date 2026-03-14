from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


class DatasetIntegrityError(RuntimeError):
    pass


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data"
SEED_ROOT = DATA_ROOT / "seed" / "tokyu"
BUILT_ROOT = DATA_ROOT / "built"
PARQUET_SCHEMA_ROOT = REPO_ROOT / "schema" / "parquet"


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _seed_missing(dataset_id: str) -> List[str]:
    required = [
        SEED_ROOT / "version.json",
        SEED_ROOT / "depots.json",
        SEED_ROOT / "route_to_depot.csv",
        SEED_ROOT / "datasets" / f"{dataset_id}.json",
    ]
    return [str(path) for path in required if not path.exists()]


def _built_required(dataset_id: str) -> Dict[str, Path]:
    built_dir = BUILT_ROOT / dataset_id
    return {
        "manifest": built_dir / "manifest.json",
        "routes": built_dir / "routes.parquet",
        "trips": built_dir / "trips.parquet",
        "timetables": built_dir / "timetables.parquet",
    }


def evaluate_dataset_integrity(dataset_id: str) -> Dict[str, Any]:
    seed_missing = _seed_missing(dataset_id)
    seed_ready = len(seed_missing) == 0

    required = _built_required(dataset_id)
    built_missing = [str(path) for path in required.values() if not path.exists()]
    manifest_payload: Dict[str, Any] | None = None
    integrity_error: str | None = None

    if required["manifest"].exists():
        try:
            manifest_payload = _read_json(required["manifest"])
        except Exception as exc:
            integrity_error = f"Invalid manifest JSON: {exc}"

    if manifest_payload:
        manifest_dataset_id = str(manifest_payload.get("dataset_id") or "").strip()
        if manifest_dataset_id and manifest_dataset_id != dataset_id:
            integrity_error = (
                f"Manifest dataset_id mismatch: expected '{dataset_id}', got '{manifest_dataset_id}'"
            )

    built_ready = seed_ready and len(built_missing) == 0 and integrity_error is None
    missing_artifacts = seed_missing + built_missing
    return {
        "dataset_id": dataset_id,
        "seed_ready": seed_ready,
        "built_ready": built_ready,
        "missing_artifacts": missing_artifacts,
        "integrity_error": integrity_error,
        "manifest": manifest_payload,
    }


def check_dataset_integrity(dataset_id: str) -> Dict[str, Any]:
    result = evaluate_dataset_integrity(dataset_id)
    if not result["seed_ready"] or result["integrity_error"] or result["missing_artifacts"]:
        raise DatasetIntegrityError(
            result["integrity_error"]
            or f"Dataset '{dataset_id}' integrity check failed: {result['missing_artifacts']}"
        )
    return result


def load_parquet_schema(name: str) -> Dict[str, Any]:
    path = PARQUET_SCHEMA_ROOT / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Parquet schema file not found: {path}")
    return _read_json(path)


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(
            value,
            bool,
        )
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return True


def validate_rows_against_schema(
    rows: Iterable[Dict[str, Any]],
    *,
    schema_name: str,
    max_errors: int = 20,
) -> List[str]:
    schema = load_parquet_schema(schema_name)
    required_columns = dict(schema.get("required_columns") or {})
    errors: List[str] = []
    for idx, row in enumerate(rows):
        if len(errors) >= max_errors:
            break
        for column, expected_type in required_columns.items():
            if column not in row:
                errors.append(f"row[{idx}] missing column '{column}'")
                if len(errors) >= max_errors:
                    break
                continue
            value = row.get(column)
            if value is None:
                errors.append(f"row[{idx}] column '{column}' is null")
                if len(errors) >= max_errors:
                    break
                continue
            if not _matches_type(value, str(expected_type)):
                errors.append(
                    f"row[{idx}] column '{column}' expected {expected_type}, got {type(value).__name__}"
                )
                if len(errors) >= max_errors:
                    break
    return errors
