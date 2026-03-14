from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import logging
import pathlib
import sys
from typing import Any


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_all")

DATA_ROOT = pathlib.Path(__file__).resolve().parents[2] / "data"
SEED_ROOT = DATA_ROOT / "seed" / "tokyu"
BUILT_ROOT = DATA_ROOT / "built"


def _load_module(module_name: str, relative_path: str) -> Any:
    module_path = pathlib.Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_stage(name: str, fn: Any, *args: Any, **kwargs: Any) -> bool:
    log.info("[%s] starting", name)
    try:
        fn(*args, **kwargs)
        log.info("[%s] done", name)
        return True
    except Exception as exc:
        log.error("[%s] FAILED: %s", name, exc)
        return False


def remove_stale_manifest(built_dir: pathlib.Path) -> None:
    manifest_path = built_dir / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
        log.info("Removed stale manifest: %s", manifest_path)


def _today() -> str:
    return datetime.date.today().isoformat()


def build_dataset(
    dataset_id: str,
    *,
    no_fetch: bool = False,
    force: bool = False,
    feed_path: str | None = None,
    strict_gtfs_reconciliation: bool = False,
) -> int:
    built_dir = BUILT_ROOT / dataset_id
    built_dir.mkdir(parents=True, exist_ok=True)

    log.info("Building dataset: %s", dataset_id)
    log.info("Output: %s", built_dir)
    remove_stale_manifest(built_dir)

    fetch_mod = _load_module("fetch_odpt", "pipeline/fetch_odpt.py")
    routes_mod = _load_module("build_routes", "pipeline/build_routes.py")
    trips_mod = _load_module("build_trips", "pipeline/build_trips.py")
    timetables_mod = _load_module("build_timetables", "pipeline/build_timetables.py")
    helper_mod = _load_module("tokyu_gtfs_built_artifacts", "pipeline/_gtfs_built_artifacts.py")
    shard_mod = _load_module("build_tokyu_shards", "pipeline/build_tokyu_shards.py")
    manifest_mod = _load_module("manifest_writer", "lib/manifest_writer.py")
    version_mod = _load_module("producer_version", "lib/producer_version.py")

    if not no_fetch:
        if not run_stage("fetch_odpt", fetch_mod.fetch_odpt, dataset_id=dataset_id):
            log.error("Build aborted at fetch stage. No manifest written.")
            return 1

    if not run_stage(
        "build_routes",
        routes_mod.build_routes,
        dataset_id=dataset_id,
        built_dir=built_dir,
        seed_root=SEED_ROOT,
        force=force,
        feed_path=feed_path,
    ):
        log.error("Build aborted at build_routes. No manifest written.")
        return 1

    if not run_stage(
        "build_trips",
        trips_mod.build_trips,
        dataset_id=dataset_id,
        built_dir=built_dir,
        seed_root=SEED_ROOT,
        feed_path=feed_path,
    ):
        log.error("Build aborted at build_trips. No manifest written.")
        return 1

    if not run_stage(
        "build_timetables",
        timetables_mod.build_timetables,
        dataset_id=dataset_id,
        built_dir=built_dir,
        seed_root=SEED_ROOT,
        feed_path=feed_path,
    ):
        log.error("Build aborted at build_timetables. No manifest written.")
        return 1

    if not run_stage(
        "build_stops",
        helper_mod.build_stops_artifact,
        dataset_id=dataset_id,
        built_dir=built_dir,
        seed_root=SEED_ROOT,
        feed_path=feed_path,
    ):
        log.error("Build aborted at build_stops. No manifest written.")
        return 1

    if not run_stage(
        "build_stop_timetables",
        helper_mod.build_stop_timetables_artifact,
        dataset_id=dataset_id,
        built_dir=built_dir,
        seed_root=SEED_ROOT,
        feed_path=feed_path,
    ):
        log.error("Build aborted at build_stop_timetables. No manifest written.")
        return 1

    if not run_stage(
        "gtfs_reconciliation",
        helper_mod.build_gtfs_reconciliation_artifact,
        dataset_id=dataset_id,
        built_dir=built_dir,
        seed_root=SEED_ROOT,
        feed_path=feed_path,
        strict=strict_gtfs_reconciliation,
    ):
        log.error("Build aborted at gtfs_reconciliation. No manifest written.")
        return 1

    if not run_stage(
        "build_tokyu_shards",
        shard_mod.build_tokyu_shards,
        dataset_id,
    ):
        log.error("Build aborted at build_tokyu_shards. No manifest written.")
        return 1

    seed_def_path = SEED_ROOT / "datasets" / f"{dataset_id}.json"
    seed_def = json.loads(seed_def_path.read_text(encoding="utf-8"))
    try:
        manifest_path = manifest_mod.write_manifest(
            built_dir=built_dir,
            dataset_id=dataset_id,
            dataset_version=_today(),
            included_depots=seed_def.get("included_depots", []),
            included_routes=seed_def.get("included_routes", "ALL"),
            seed_version_path=SEED_ROOT / "version.json",
            producer_version=version_mod.get_producer_version(),
            min_runtime_version=version_mod.get_min_runtime_version(),
        )
        log.info("Manifest written: %s", manifest_path)
    except Exception as exc:
        log.error("Manifest write failed: %s", exc)
        return 1

    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
        from src.artifact_contract import check_artifact_contract

        check_artifact_contract(built_dir, verify_hashes=True)
        log.info("Contract validation passed.")
    except Exception as exc:
        log.error("Contract validation FAILED after build: %s", exc)
        log.error("The built artifacts were written but the runtime contract check failed.")
        return 2

    log.info("Build complete: %s", dataset_id)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, choices=["tokyu_core", "tokyu_full"])
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--feed-path", default="")
    parser.add_argument("--strict-gtfs-reconciliation", action="store_true")
    args = parser.parse_args()

    return build_dataset(
        args.dataset,
        no_fetch=args.no_fetch,
        force=args.force,
        feed_path=args.feed_path or None,
        strict_gtfs_reconciliation=args.strict_gtfs_reconciliation,
    )


if __name__ == "__main__":
    sys.exit(main())
