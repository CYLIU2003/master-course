from __future__ import annotations

import importlib.util
from pathlib import Path


def main() -> int:
    source_path = Path(__file__).resolve().parents[3] / "data_prep" / "pipeline" / "build_all.py"
    spec = importlib.util.spec_from_file_location("root_data_prep_build_all", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load build_all from {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
