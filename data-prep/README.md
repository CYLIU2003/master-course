# data-prep

This is the producer application. It is independent of the main research app.

## What lives here

- `lib/tokyubus_gtfs/` - GTFS parsing and canonicalization (offline only)
- `lib/catalog_builder/` - ODPT/GTFS fetch and catalog build helpers (offline only)
- `pipeline/` - ETL scripts: fetch -> normalize -> export built artifacts
- `api/main.py` - optional FastAPI explorer for build validation

## What this app produces

Output goes to `data/built/<dataset_id>/`:

- `manifest.json`
- `routes.parquet`
- `trips.parquet`
- `timetables.parquet`
- `gtfs_reconciliation.json`

## What this app does NOT do

- It does not serve the research frontend
- It does not run the optimizer
- It does not share a live database with the main app
- It does not need to be running when the main app runs

## Quick build

```bash
# Run from the repository root
python -m data_prep.pipeline.build_all --dataset tokyu_core

# Or run from inside data-prep/ via the compatibility wrapper
cd data-prep
python -m data_prep.pipeline.build_all --dataset tokyu_core

# Full build (fetch + build all + write manifest + validate)
python -m data_prep.pipeline.build_all --dataset tokyu_core

# Skip ODPT fetch (use existing raw cache)
python -m data_prep.pipeline.build_all --dataset tokyu_core --no-fetch

# Fail if GTFS/TokyuBus-GTFS does not fully match the authoritative route master
python -m data_prep.pipeline.build_all --dataset tokyu_core --no-fetch --strict-gtfs-reconciliation

# Build full dataset
python -m data_prep.pipeline.build_all --dataset tokyu_full --no-fetch
```

The compatibility package under `data-prep/data_prep/` forwards execution to the
root `data_prep` package so the module path works from either working directory.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success - manifest written and contract validated |
| 1 | Stage failure - build aborted, manifest NOT written |
| 2 | Artifacts written but contract validation failed |

## Build guarantees

- Manifest is written only after the required Parquet files succeed
- `build_all` also emits `stops.parquet` and `stop_timetables.parquet` so scenario bootstrap can hydrate stop master data and stop timetable links from the built dataset itself
- Any stale manifest from a previous run is removed at build start
- The runtime contract check is run immediately after manifest write
- `gtfs_reconciliation.json` is written on every build so route-master vs GTFS mismatches are visible
- A build that exits non-zero will not produce a manifest that tricks the runtime into `built_ready=True`

## If a build fails partway

- Exit code `1`: inspect the failing stage log, fix the producer-side issue, then rerun `python -m data_prep.pipeline.build_all --dataset <dataset_id>`
- Exit code `2`: artifacts were written but the runtime contract check failed; inspect `data/built/<dataset_id>/manifest.json`, rebuild, and confirm the runtime accepts the dataset
- If a previous manifest existed, it is removed at build start, so the runtime will stay in `built_ready=false` until a successful build writes a new manifest
