from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path


MANIFEST_SCHEMA_VERSION = "v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json_file(path: Path) -> str:
    return sha256_file(path)


def write_manifest(
    built_dir: Path,
    dataset_id: str,
    dataset_version: str,
    included_depots: list[str],
    included_routes: list[str] | str,
    seed_version_path: Path,
    producer_version: str,
    min_runtime_version: str,
    source: str = "odpt + mapping inputs",
) -> Path:
    artifact_names = ["routes.parquet", "trips.parquet", "timetables.parquet"]
    optional_artifacts = ["stops.parquet", "stop_timetables.parquet"]

    for name in artifact_names:
        path = built_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Cannot write manifest: artifact not found: {path}")

    artifact_names.extend(
        [name for name in optional_artifacts if (built_dir / name).exists()]
    )

    try:
        import pandas as pd

        row_counts = {
            name.replace(".parquet", ""): len(pd.read_parquet(built_dir / name))
            for name in artifact_names
        }
    except Exception:
        row_counts = {name.replace(".parquet", ""): -1 for name in artifact_names}

    manifest = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
        "source": source,
        "included_depots": included_depots,
        "included_routes": included_routes,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "producer_version": producer_version,
        "min_runtime_version": min_runtime_version,
        "seed_hash": sha256_json_file(seed_version_path),
        "artifact_hashes": {
            name: sha256_file(built_dir / name)
            for name in artifact_names
        },
        "row_counts": row_counts,
        "schema_versions": {
            "routes": "v1",
            "trips": "v1",
            "timetables": "v1",
            **(
                {"stops": "v1"}
                if (built_dir / "stops.parquet").exists()
                else {}
            ),
            **(
                {"stop_timetables": "v1"}
                if (built_dir / "stop_timetables.parquet").exists()
                else {}
            ),
        },
    }

    output_path = built_dir / "manifest.json"
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path
