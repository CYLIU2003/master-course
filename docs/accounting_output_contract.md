# Accounting Output Contract

## Canonical files

| File | Meaning |
|---|---|
| `vehicle_slot_ledger.csv` | Vehicle-by-slot operational ledger |
| `vehicle_slot_ledger.json` | JSON form of the same ledger |
| `energy_flow_ledger.csv` | Depot-by-slot PV / BESS / grid ledger |
| `energy_flow_ledger.json` | JSON form of the same ledger |
| `kpi_summary.json` | Aggregated summary derived from the ledgers |

## Key rules

- `vehicle_slot_ledger` is the source for vehicle totals, SOC tracking, charging input, and trip counts.
- `energy_flow_ledger` is the source for PV, BESS, grid import, peak kW, and TOU energy cost.
- `kpi_summary.json` must be derived from the ledgers, not from independent summary logic.
- Rounding is only for presentation.
- Missing provenance must be explicit, not silently inferred in downstream summaries.

## Validation

Use:

```bash
python -m src.optimization.accounting.validate_outputs --scenario-dir <scenario-dir> --strict
```

Strict mode exits non-zero on any conservation or summary mismatch.

