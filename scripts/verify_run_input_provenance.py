"""Verify the scenario, Prepare, and parameter provenance of a dated run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.services.optimization_run.input_provenance import (  # noqa: E402
    VALIDATION_FILE,
    validate_run_input_provenance,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--skip-prepared-source",
        action="store_true",
        help="Verify only the compact run bundle without rehashing the large prepared file.",
    )
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    result = validate_run_input_provenance(
        run_dir,
        verify_prepared_source=not args.skip_prepared_source,
    )
    (run_dir / VALIDATION_FILE).write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
