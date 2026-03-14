from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_module(module_name: str, relative_path: str) -> Any:
    if module_name in sys.modules:
        return sys.modules[module_name]
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

def build_timetables(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
    feed_path: str | Path | None = None,
) -> None:
    del feed_path
    helper = _load_module(
        "tokyu_gtfs_built_artifacts",
        "pipeline/_gtfs_built_artifacts.py",
    )
    helper.build_timetables_artifact(
        dataset_id=dataset_id,
        built_dir=built_dir,
        seed_root=seed_root,
    )


def write_manifest_for_dataset(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
    dataset_version: str,
) -> Path:
    manifest_writer = _load_module("manifest_writer", "lib/manifest_writer.py")
    producer_version = _load_module("producer_version", "lib/producer_version.py")
    definition = _load_module(
        "tokyu_gtfs_built_artifacts",
        "pipeline/_gtfs_built_artifacts.py",
    )._read_dataset_definition(seed_root, dataset_id)
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
    parser.add_argument("--feed-path", default="")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    built_dir = repo_root / "data" / "built" / args.dataset
    seed_root = repo_root / "data" / "seed" / "tokyu"
    build_timetables(args.dataset, built_dir, seed_root, feed_path=args.feed_path or None)
    if args.dataset_version:
        write_manifest_for_dataset(args.dataset, built_dir, seed_root, args.dataset_version)


if __name__ == "__main__":
    main()
