# Literature-aligned figure and CSV contract

Status: **CURRENT**
Applies to: ordinary frontend runs with an executed and accepted hourly
Rolling chain

## Purpose

Each finalized run produces newly rendered plots that expose the same kinds of
relationships examined in the local literature under `先行文献/`. The system
does not copy a paper figure and does not infer unavailable experimental
results. Every plotted value is traceable to an accepted Rolling prefix,
independent physical-event validation, or the canonical executed-day ledger.

The bundle is written to:

```text
graph/literature_figures/
```

Successful figure generation does not make a run teacher-ready. The bundle
preserves `teacher_release_status`, `research_submission_ready`, and all
blocking reasons.

## Generated single-run figures

| Output | Local literature analogue | Canonical evidence |
|---|---|---|
| `01_vehicle_operation_timeline.(png\|svg)` | No42 Fig. 7; No16 Fig. 3 | `graph/vehicle_event_timeline.csv` |
| `02_bev_soc_profiles.(png\|svg)` | No55 Fig. 6; No16 Fig. 5; No61 Fig. 4 | `graph/vehicle_soc_event_timeline.csv` |
| `03_energy_management_profile.(png\|svg)` | No61 Figs. 7–9; IEEJ rolling Figs. 2–3; No16 Figs. 4, 8 | accepted Rolling hourly flows, canonical cost/CO2 time series |
| `04_charger_occupancy_heatmap.(png\|svg)` | No42 charger-conflict formulation | physical charger occupancy timeline |
| `05_cost_and_emissions.(png\|svg)` | No16 Fig. 6; No55 Table 5 | executed-day canonical cost ledger |

Each figure has a sibling `*_source.csv` containing exactly the values sent to
Matplotlib. Full vehicle IDs remain in CSV even when compact plot labels are
used.

## Analysis-ready raw CSV bundle

`graph/literature_figures/raw_data/` contains:

1. executed vehicle events;
2. independently reconstructed BEV SOC events;
3. physical charger sessions;
4. original accepted hourly Rolling energy flows;
5. canonical cost time series;
6. canonical CO2 time series;
7. final vehicle-trip assignment and timetable rows;
8. accepted executed charging-source rows before physical session aggregation;
9. normalized hourly PV/BESS/grid/price/carbon data;
10. active vehicle parameters;
11. canonical cost components;
12. canonical CO2 components;
13. physical validation metrics;
14. executed-day accounting metrics;
15. excluded vehicle records and reasons; and
16. `raw_data_catalog.csv`, which records row count, evidence level, canonical
    source, and meaning for every dataset.

The canonical-copy CSV files preserve source values. JSON-to-CSV exports only
flatten named mappings; they never rescale SOC, energy, fuel, distance, cost,
or emissions. The bundle manifest stores the size and SHA-256 of every plot,
table, and raw CSV.

## Outputs that require more than one run

The following are not generated from a single run:

- high-PV versus low-PV/no-PV comparison;
- Monte Carlo uncertainty distributions;
- PV/BESS/charger-capacity sensitivity curves; and
- runtime distributions.

`figure_eligibility.csv` marks these as requiring paired runs, a parameter
sweep, or repeated experiments. A future comparison renderer must consume
accepted pair/manifold manifests and must not join runs by filename or label
alone.

## Reference mapping

The local reference mapping records source file hash, citation, relevant PDF
pages, and the adapted analytical relationship in
`literature_source_mapping.csv`. Current mappings include:

- No42, *Transportation Research Part D* 115 (2023), pp. 9 and 11;
- No55, *Transportation Research Part D* 117 (2023), pp. 17 and 19;
- No16, *Frontiers of Engineering Management* 11(4) (2024), pp. 11–14;
- No61, *Transportation Research Part D* 150 (2026), pp. 12, 15, and 16; and
- the 2025 IEEJ rolling-charging study, p. 2.

The local PDFs are input literature, not run artifacts. Their hashes are
recorded when available, but absence of the ignored local PDF directory does
not alter solver results or the generated-data evidence.
