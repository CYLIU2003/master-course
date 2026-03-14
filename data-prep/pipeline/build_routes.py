from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pandas as pd


def build_routes(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
    force: bool = False,
) -> None:
    built_dir.mkdir(parents=True, exist_ok=True)
    output_path = built_dir / "routes.parquet"
    if output_path.exists() and not force:
        output_path.unlink()

    definition = json.loads(
        (seed_root / "datasets" / f"{dataset_id}.json").read_text(encoding="utf-8")
    )
    included_depots = {str(item) for item in definition.get("included_depots") or []}
    included_routes = definition.get("included_routes")
    route_filter = None if included_routes == "ALL" else {str(item) for item in included_routes or []}

    rows = []
    with (seed_root / "route_to_depot.csv").open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            depot_id = str(row.get("depot_id") or "").strip()
            route_code = str(row.get("route_code") or "").strip()
            if not depot_id or not route_code:
                continue
            if included_depots and depot_id not in included_depots:
                continue
            if route_filter is not None and route_code not in route_filter:
                continue
            rows.append(
                {
                    "id": f"tokyu:{depot_id}:{route_code}",
                    "routeCode": route_code,
                    "routeLabel": route_code,
                    "name": route_code,
                    "depotId": depot_id,
                    "source": "seed_build",
                    "enabled": True,
                }
            )

    pd.DataFrame(rows).to_parquet(output_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    build_routes(
        dataset_id=args.dataset,
        built_dir=repo_root / "data" / "built" / args.dataset,
        seed_root=repo_root / "data" / "seed" / "tokyu",
        force=args.force,
    )


if __name__ == "__main__":
    main()
