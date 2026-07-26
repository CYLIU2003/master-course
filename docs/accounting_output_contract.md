# Accounting Output Contract

## Canonical files

| File | Meaning |
|---|---|
| `movement_event_ledger.csv` | Unique startup / connection / terminal-return movements |
| `movement_event_ledger.json` | JSON form of the same movement ledger |
| `vehicle_slot_ledger.csv` | Vehicle-by-slot operational ledger |
| `vehicle_slot_ledger.json` | JSON form of the same ledger |
| `energy_flow_ledger.csv` | Depot-by-slot PV / BESS / grid ledger |
| `energy_flow_ledger.json` | JSON form of the same ledger |
| `kpi_summary.json` | Aggregated summary derived from the ledgers |

## Key rules

- `movement_event_ledger` is the primary record for non-service distance,
  BEV energy, ICE fuel, and ICE CO2. Each `event_id` is unique. A connection
  belongs to the following trip and must not also be copied to the preceding
  trip's `deadhead_after`.
- `vehicle_slot_ledger` is the slot allocation of service rows and movement
  events, and is the source for vehicle totals, SOC tracking, charging input,
  and trip counts.
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

