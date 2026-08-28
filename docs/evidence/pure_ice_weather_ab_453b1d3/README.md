# Pure-ICE weather A/B review evidence (`453b1d3`)

This directory is the review-sized, Git-tracked subset of the completed
20-process experiment.  Files were copied byte-for-byte from
`output/diagnostics/pure_ice_weather_ab_453b1d3_20260827/` after its 103-entry
SHA-256 index passed with zero missing files and zero mismatches.  No solver was
rerun to publish this subset.

## Provenance

- Numerical execution SHA: `453b1d340311de109645d006b9ec5a0de2788c2e`
- Frozen tag: `thesis-pure-ice-weather-ab-453b1d3`
- Documentation HEAD immediately after the experiment:
  `abf149d3dbc3909e40361ada3c9a8542c1cf1dd5`
- SUNNY scenario: `771d115b-75b0-49f7-a7f0-25f259a2cd21`
- RAIN scenario: `b23fd26c-1233-4c73-bb9e-bdb8b1584760`
- Full-bundle `artifact_hashes.json` SHA-256:
  `f6b7232164ee2ed9df5f9cf7b005f25a5f25c1c6f3699240acae05b41bcbe672`

The two scenario names are labels for a same-service-day PV counterfactual,
not two observed operating days:

- SUNNY uses the `2025-08-05` WEEKDAY timetable and the `2025-08-05` PV
  profile.
- RAIN keeps the same `2025-08-05` WEEKDAY timetable and substitutes the PV
  profile sourced from `2025-08-10` under the
  `fixed_weekday_timetable_pv_counterfactual` contract.

## Frozen experiment controls

- Phase: `phase3_two_stage`
- Internal timestep / Rolling step: 15 / 60 minutes
- Candidate limit / composition-search radius: `1 / 0`
- Stage-1 / Stage-2 / total child limits: 435 / 30 / 585 seconds
- Requested MIP gap: 10%
- Random seed / Gurobi threads: 42 / 1
- Stage-1 powertrain selector: OFF
- Stage-1 BestObjStop: OFF
- Weather operation policy: OFF
- Schedule: five alternating AB/BA pairs per scenario, one isolated child
  process per run

Accordingly, this bundle compares representations A and B.  It is not a 1%
optimality experiment and does not test broad powertrain-composition search.

## Result

All 20 children served 264/264 trips and passed physical validation, 24/24
Rolling, accounting, fleet/provenance, and no-fallback/no-repair gates.  Every
aggregate-B child also passed its exact recovery and feasible-set invariance
checks.  Both scenarios therefore have the bounded verdict
`PASS_STRUCTURAL_ONLY`.

Aggregate B reduced the median model size relative to discrete A:

- total variables: 825,858 to 583,125 (-29.392%)
- binary variables: 726,240 to 493,756 (-32.012%)
- constraints: 151,574 to 125,547 (-17.171%)
- nonzeros: 16,316,201 to 15,753,121 (-3.451%)

It did not improve certified gap, incumbent, or node count.  Median solver time
worsened from 30.754 to 435.106 seconds in SUNNY and from 31.887 to 435.103
seconds in RAIN.  Aggregate B remains default-OFF.

## Published files

- [`weather_ab_result.json`](weather_ab_result.json): terminal status, counts,
  scenario verdicts, and input-contract result.
- [`SUNNY_repeated_comparison.json`](SUNNY_repeated_comparison.json) and
  [`RAIN_repeated_comparison.json`](RAIN_repeated_comparison.json): all five
  A/B pair metrics and provenance. CSV and Markdown views are included.
- [`weather_cross_scenario_comparison.json`](weather_cross_scenario_comparison.json):
  fixed-control SUNNY/RAIN comparison. CSV and Markdown views are included.
- [`request_manifest.json`](request_manifest.json): runtime environment,
  prepared-input hashes, scenario semantics, solver controls, and execution
  schedule.
- [`fresh_prepare_manifest.json`](fresh_prepare_manifest.json): Fresh Prepare
  identities and response checks.
- [`artifact_hashes.json`](artifact_hashes.json): authoritative SHA-256 index of
  the complete 103-file local bundle.

The full raw bundle is intentionally not committed because it contains all 20
run directories.  The repository now exposes the main review evidence and the
complete file/hash inventory; a durable external archive for the full raw
bundle remains a separate publication task.

## Integrity check without solving

From the repository root:

```powershell
$evidence = "docs/evidence/pure_ice_weather_ab_453b1d3"
Get-FileHash "$evidence/weather_ab_result.json" -Algorithm SHA256
Get-FileHash "$evidence/request_manifest.json" -Algorithm SHA256
Get-FileHash "$evidence/fresh_prepare_manifest.json" -Algorithm SHA256
```

Expected hashes are respectively:

- `f041658da3b24f9815cb558cba00cb2aec2aab7f2682ae56244bbefe019baef7`
- `d0f65c2232d73edfb057fc0c417fa969f726c44b8a09fcd31e4165368bd5659b`
- `613a51bc9701d93ab7114c4305c6758523a345f4b2a87754b8969352f3a3ec32`

## Full reproduction command

This is provenance, not a request to rerun the completed study.  A deliberate
reproduction must start the BFF from a clean checkout of the frozen tag and use
a new empty output directory:

```powershell
.\.venv\Scripts\python.exe scripts\run_pure_ice_aggregation_weather_ab.py `
  --base-url http://127.0.0.1:8010 `
  --output-dir output\diagnostics\pure_ice_weather_ab_453b1d3_<new-date> `
  --sunny-prepare-request config\research\pure_ice_weather_ab\sunny_prepare_request.json `
  --rain-prepare-request config\research\pure_ice_weather_ab\rain_prepare_request.json `
  --optimization-request-template config\research\pure_ice_weather_ab\optimization_request_template.json `
  --stage1-time-limit-seconds 435 `
  --stage2-time-limit-seconds 30 `
  --small-exact-parity-passed
```

## Claim boundary

Supported: correctness parity for the tested scenarios, exact physical
recovery of aggregate ICE paths, structural/RSS reduction, and the observed
runtime regression.

Not supported: solver speedup, optimality improvement, a 264-trip integrated
global optimum, a 1%-optimal result, endogenous weather-driven fleet search,
or a general SUNNY/RAIN operating conclusion.
