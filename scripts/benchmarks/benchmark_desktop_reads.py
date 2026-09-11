"""Measure bounded desktop reads on synthetic large artifacts, never real inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pyarrow as pa
import pyarrow.parquet as pq
from bff.store import desktop_store, scenario_meta_store, scenario_store, trip_store


def measured(action):
    tracemalloc.start()
    started = time.perf_counter()
    value = action()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return value, {"seconds": elapsed, "python_peak_bytes": peak}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1_000_000)
    args = parser.parse_args()
    if args.rows < 250:
        parser.error("--rows must be at least 250")
    parent = ROOT / "output" / "desktop_scalability"
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="synthetic-", dir=parent))
    refs = scenario_meta_store.default_refs(output, "synthetic")
    scenario_meta_store.save_meta(
        output,
        "synthetic",
        {"meta": {"id": "synthetic", "name": "Synthetic benchmark"}, "refs": refs},
    )
    db_path = Path(refs["artifactStore"])
    trip_store.save_timetable_rows(db_path, [])
    with sqlite3.connect(db_path) as conn:

        def rows():
            for i in range(args.rows):
                row = {
                    "trip_id": f"synthetic-{i}",
                    "route_id": "test-route",
                    "service_id": "WEEKDAY",
                    "departure": "05:00",
                    "arrival": "06:00",
                    "operator_id": "SYNTHETIC",
                    "distance_km": 12.0,
                }
                yield (
                    i,
                    "WEEKDAY",
                    "test-route",
                    "05:00",
                    "06:00",
                    json.dumps(row, separators=(",", ":")),
                )

        conn.executemany("INSERT INTO timetable_rows VALUES (?,?,?,?,?,?)", rows())
    parquet_path = Path(refs["tripSet"])
    schema = pa.schema([("row_index", pa.int64()), ("payload_json", pa.string())])
    with pq.ParquetWriter(parquet_path, schema) as writer:
        for start in range(0, args.rows, 16384):
            stop = min(start + 16384, args.rows)
            writer.write_table(
                pa.table(
                    {
                        "row_index": list(range(start, stop)),
                        "payload_json": [
                            json.dumps({"id": i}) for i in range(start, stop)
                        ],
                    },
                    schema=schema,
                )
            )
    result_path = Path(refs["optimizationResult"])
    with result_path.open("w", encoding="utf-8") as file:
        file.write('{"solver_status":"SYNTHETIC","trajectory":[')
        for i in range(args.rows):
            if i:
                file.write(",")
            file.write('{"vehicle_id":"synthetic","soc":50}')
        file.write(
            '],"objective_value":0,"solution_validity":{"research_acceptance_status":"NOT_REQUESTED"}}'
        )
    scenario_store._STORE_DIR = output  # This process's synthetic store only.
    page, sql_measure = measured(
        lambda: desktop_store.table_page(
            "synthetic", "timetable_rows", args.rows - 250, 250
        )
    )
    parquet, parquet_measure = measured(
        lambda: trip_store.page_parquet_rows(
            parquet_path, offset=args.rows - 250, limit=250
        )
    )
    result, result_measure = measured(lambda: desktop_store.result_summary("synthetic"))
    _, cached_measure = measured(lambda: desktop_store.result_summary("synthetic"))
    checks = {
        "sql_exact_page": page["total"] == args.rows
        and page["items"][0]["trip_id"] == f"synthetic-{args.rows - 250}"
        and len(page["items"]) == 250,
        "parquet_exact_page": parquet
        == [{"id": i} for i in range(args.rows - 250, args.rows)],
        "result_zero_preserved": result["values"]["objective_value"] == 0,
        "trajectory_not_sent": "trajectory" not in result["values"],
        "bounded_python_memory": max(
            sql_measure["python_peak_bytes"],
            parquet_measure["python_peak_bytes"],
            result_measure["python_peak_bytes"],
        )
        < 10 * 1024 * 1024,
    }
    summary = {
        "scope": "synthetic read benchmark, not a solver/research result",
        "rows": args.rows,
        "checks": checks,
        "sqlite_page": sql_measure,
        "parquet_deep_page": parquet_measure,
        "result_projection": result_measure,
        "cached_result_projection": cached_measure,
        "sqlite_bytes": db_path.stat().st_size,
        "result_json_bytes": result_path.stat().st_size,
        "page_json_bytes": len(json.dumps(page).encode()),
        "memory_scope": "Python allocations during reads; excludes SQLite/Arrow native allocations and dataset construction",
    }
    (output / "benchmark.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(output / "benchmark.json"), **summary}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
