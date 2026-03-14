from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Iterable
from typing import Any

import pandas as pd


def _load_module(module_name: str, relative_path: str) -> Any:
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coalesce_scalar(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return value if value else default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return value


def _coalesce_sequence(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [value] if value else list(default)
    if isinstance(value, Iterable):
        items = [str(item) for item in value if item is not None and str(item)]
        return items or list(default)
    return list(default)


def build_timetables(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
) -> None:
    del seed_root
    built_dir.mkdir(parents=True, exist_ok=True)
    trips_path = built_dir / "trips.parquet"
    if not trips_path.exists():
        raise FileNotFoundError(f"Trips artifact not found: {trips_path}")

    trips = pd.read_parquet(trips_path)
    timetable_rows = []
    for trip in trips.to_dict(orient="records"):
        timetable_rows.append(
            {
                "trip_id": trip.get("trip_id"),
                "route_id": trip.get("route_id"),
                "service_id": trip.get("service_id"),
                "origin": _coalesce_scalar(trip.get("origin"), "origin"),
                "destination": _coalesce_scalar(trip.get("destination"), "destination"),
                "departure": _coalesce_scalar(trip.get("departure"), "06:00:00"),
                "arrival": _coalesce_scalar(trip.get("arrival"), "06:30:00"),
                "distance_km": _coalesce_scalar(trip.get("distance_km"), 0.0),
                "allowed_vehicle_types": _coalesce_sequence(
                    trip.get("allowed_vehicle_types"),
                    ["BEV", "ICE"],
                ),
                "source": "seed_build",
            }
        )

    pd.DataFrame(timetable_rows).to_parquet(built_dir / "timetables.parquet", index=False)


def write_manifest_for_dataset(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
    dataset_version: str,
) -> Path:
    manifest_writer = _load_module("manifest_writer", "lib/manifest_writer.py")
    producer_version = _load_module("producer_version", "lib/producer_version.py")
    definition = json.loads(
        (seed_root / "datasets" / f"{dataset_id}.json").read_text(encoding="utf-8")
    )
    return manifest_writer.write_manifest(
        built_dir=built_dir,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        included_depots=list(definition.get("included_depots") or []),
        included_routes=definition.get("included_routes") or "ALL",
        seed_version_path=seed_root / "version.json",
        producer_version=producer_version.get_producer_version(),
        min_runtime_version=producer_version.get_min_runtime_version(),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--dataset-version", default="")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    built_dir = repo_root / "data" / "built" / args.dataset
    seed_root = repo_root / "data" / "seed" / "tokyu"
    build_timetables(args.dataset, built_dir, seed_root)
    if args.dataset_version:
        write_manifest_for_dataset(args.dataset, built_dir, seed_root, args.dataset_version)


if __name__ == "__main__":
    main()
