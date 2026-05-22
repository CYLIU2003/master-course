# Accounting Dataflow Audit

## Scope

This audit covers the canonical optimization accounting path used by the BFF export flow.

## Current canonical flow

1. `OptimizationEngine.solve(...)` produces the finalized plan.
2. `bff/routers/optimization.py` materializes canonical rows:
   - `vehicle_timeline.csv`
   - `soc_events.csv`
   - `depot_power_timeseries_5min.csv`
   - `vehicle_charging_source_timeseries.csv`
   - `vehicle_soc_timeseries.csv`
   - `trip_assignment.csv`
   - `energy_flow_timeseries.csv`
3. `src/optimization/accounting/build_accounting_artifacts(...)` builds:
   - `vehicle_slot_ledger`
   - `energy_flow_ledger`
   - `kpi_summary`
4. `src/optimization/accounting/export.py` writes the canonical ledger files and summary JSON.
5. `src/optimization/accounting/validate_outputs.py` checks conservation and summary consistency.

## Canonical outputs

- `graph/vehicle_slot_ledger.csv`
- `graph/vehicle_slot_ledger.json`
- `graph/energy_flow_ledger.csv`
- `graph/energy_flow_ledger.json`
- `graph/kpi_summary.json`

Top-level run outputs mirror the graph summary where available.

## Notes

- Vehicle-level totals are aggregated from the vehicle slot ledger.
- Depot-level energy flows are aggregated from the energy flow ledger.
- Summary files no longer need to recompute the same values independently.
- Missing provenance is recorded explicitly as `inferred`.

