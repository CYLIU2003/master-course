from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def build_trips(
    dataset_id: str,
    built_dir: Path,
    seed_root: Path,
) -> None:
    del dataset_id, seed_root
    built_dir.mkdir(parents=True, exist_ok=True)
    routes_path = built_dir / "routes.parquet"
    if not routes_path.exists():
        raise FileNotFoundError(f"Routes artifact not found: {routes_path}")

    routes = pd.read_parquet(routes_path)
    trip_rows = []
    for idx, route in enumerate(routes.to_dict(orient="records"), start=1):
        route_id = str(route.get("id") or "")
        route_code = str(route.get("routeCode") or "")
        trip_rows.append(
            {
                "trip_id": f"{route_code}:trip:{idx:03d}",
                "route_id": route_id,
                "service_id": "WEEKDAY",
                "departure": "06:00:00",
                "arrival": "06:30:00",
                "origin": route_code,
                "destination": route_code,
                "distance_km": 0.0,
                "allowed_vehicle_types": ["BEV", "ICE"],
                "source": "seed_build",
            }
        )

    pd.DataFrame(trip_rows).to_parquet(built_dir / "trips.parquet", index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    build_trips(
        dataset_id=args.dataset,
        built_dir=repo_root / "data" / "built" / args.dataset,
        seed_root=repo_root / "data" / "seed" / "tokyu",
    )


if __name__ == "__main__":
    main()
