from __future__ import annotations

import importlib.util
from pathlib import Path


def main() -> int:
    source_path = Path(__file__).resolve().parents[2] / "data-prep" / "pipeline" / "build_tokyu_shards.py"
    spec = importlib.util.spec_from_file_location("data_prep_build_tokyu_shards", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load build_tokyu_shards from {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
