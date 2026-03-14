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


def build_routes(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
    force: bool = False,
    feed_path: str | Path | None = None,
) -> None:
    helper = _load_module(
        "tokyu_gtfs_built_artifacts",
        "pipeline/_gtfs_built_artifacts.py",
    )
    helper.build_routes_artifact(
        dataset_id=dataset_id,
        built_dir=built_dir,
        seed_root=seed_root,
        force=force,
        feed_path=feed_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--feed-path", default="")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    build_routes(
        dataset_id=args.dataset,
        built_dir=repo_root / "data" / "built" / args.dataset,
        seed_root=repo_root / "data" / "seed" / "tokyu",
        force=args.force,
        feed_path=args.feed_path or None,
    )


if __name__ == "__main__":
    main()
