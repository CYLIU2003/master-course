# Phase 3.5 Legacy Classification

## Move

- `src/tokyubus_gtfs/*` -> `data-prep/lib/tokyubus_gtfs/*`
- `src/gtfs_runtime/*` -> `data-prep/lib/gtfs_runtime/*`
- `src/feed_identity.py` -> `data-prep/lib/feed_identity.py`
- `src/dispatch/odpt_adapter.py` -> `data-prep/lib/catalog_builder/odpt_adapter.py`
- `bff/services/gtfs_import.py` -> `data-prep/lib/catalog_builder/gtfs_import.py`
- `bff/services/odpt_fetch.py` -> `data-prep/lib/catalog_builder/odpt_fetch.py`
- `bff/services/odpt_normalize.py` -> `data-prep/lib/catalog_builder/odpt_normalize.py`
- `bff/services/odpt_routes.py` -> `data-prep/lib/catalog_builder/odpt_routes.py`
- `bff/services/odpt_stops.py` -> `data-prep/lib/catalog_builder/odpt_stops.py`
- `bff/services/odpt_stop_timetables.py` -> `data-prep/lib/catalog_builder/odpt_stop_timetables.py`
- `bff/services/odpt_timetable.py` -> `data-prep/lib/catalog_builder/odpt_timetable.py`
- `bff/services/transit_catalog.py` -> `data-prep/lib/catalog_builder/transit_catalog.py`
- `bff/services/transit_db.py` -> `data-prep/lib/catalog_builder/transit_db.py`
- `bff/services/runtime_catalog.py` -> `data-prep/lib/catalog_builder/runtime_catalog.py`
- `bff/services/runtime_paths.py` -> `data-prep/lib/catalog_builder/runtime_paths.py`

## Delete

- `bff/routers/catalog.py` (legacy catalog refresh API)
- `bff/routers/public_data.py` (legacy public data sync API)
- `bff/tests/test_transit_catalog.py`
- Legacy runtime tests removed under `tests/`:
  - `tests/test_bff_gtfs_import.py`
  - `tests/test_bff_odpt_import_flow.py`
  - `tests/test_bff_odpt_routes.py`
  - `tests/test_bff_odpt_stop_timetables.py`
  - `tests/test_bff_odpt_timetable.py`
  - `tests/test_catalog_route_families.py`
  - `tests/test_fast_catalog_ingest.py`
  - `tests/test_gtfs_runtime_loader.py`
  - `tests/test_odpt_fetch_normalize.py`
  - `tests/test_tokyubus_gtfs_pipeline.py`
  - `tests/test_transit_db_feed_identity.py`

## Split

- `bff/routers/scenarios.py`
  - kept runtime-safe scenario CRUD/timetable/stop-timetable/calendar/rules endpoints
  - removed runtime feed ingestion and runtime snapshot import paths
- `bff/routers/master_data.py`
  - kept runtime-safe depots/vehicles/routes/stops/permissions endpoints
  - removed runtime feed import endpoints and ETL helpers
