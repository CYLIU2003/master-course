# Weather-dispatch Case A review evidence (`3ec8714`)

This directory is a Git-tracked review subset copied byte-for-byte from
`output/diagnostics/weather_dispatch_diagnosis_20260827/`. The source
73-file SHA-256 index was verified with zero missing files and zero mismatches
before copying. No solver or fixed-dispatch recourse evaluation was rerun for
publication.

## Provenance

- Frozen pure-ICE discrete-A source: numerical execution SHA `453b1d3`
- Expanded discrete candidate discovery: SHA `4c92867b`
- Public normal-path SUNNY/RAIN confirmation: SHA `ba5ac4a`
- Final cross-weather audit/documentation: SHA `3ec8714`
- Read-only confirmation re-audit: SHA `b18cf48`
- Source `artifact_hashes.json` SHA-256:
  `68244b2c57f8f2055c1751f91e2d946a08b1a876830ccc6fd321eb3894c96981`

SUNNY and RAIN use the same 2025-08-05 WEEKDAY service. RAIN substitutes the
PV profile sourced from 2025-08-10; it is not an observed Sunday-service case.

## Evidence

- `cross_weather_fixed_dispatch_matrix.*` contains all 44 fixed-assignment
  recourse evaluations (22 assignments under each PV case).
- `case_a_candidate_selection_audit.*` records candidate provenance,
  canonical ranking, winner hashes, and all declared Case A checks.
- `confirmation_manifest.json` records the clean public-path SUNNY and RAIN
  runs at `ba5ac4a`.
- `normal_confirmation_input_contract.*` compares the public-path input hashes
  with the frozen discrete-A baselines.
- `artifact_hashes.json` is the full 73-file source-bundle index.
- `normal_confirmation_reaudit_b18cf48.json` re-finalizes the two existing
  public-path runs under the stricter confirmation gates without running a
  solver. It requires accepted day-ahead research status, every shared
  Rolling acceptance check, all seven effective candidate/frontier controls,
  and the authoritative executed-day accounting cost.
- `normal_confirmation_input_contract_reaudit_b18cf48.*` fails closed on 22
  explicitly required hashes on both the frozen-A and confirmation sides;
  it no longer derives the contract from whichever baseline keys happen to
  be present.
- `case_a_candidate_selection_audit_reaudit_b18cf48.*` and
  `reaudit_source_artifact_hashes_b18cf48.json` preserve the updated Case-A
  audit and its complete source-file hash inventory.
- `goal_completion_audit.md` and `weather_dispatch_diagnosis_report.md` are the
  frozen human-readable audit views.

## Result and claim boundary

Within these two fixed counterfactual scenarios, the accepted 22-candidate
union has different canonical fixed-dispatch winners for SUNNY and RAIN. This
supports the bounded diagnosis that the earlier identical winner was caused
by insufficient candidate coverage (Case A).

It does not establish an integrated global optimum, a general weather benefit,
causal deployment performance, or a 1%-optimal solution. The confirmed
Phase-3 certified gaps remain 9.5213476% for SUNNY and 1.6563581% for RAIN.
The authoritative 24-hour Rolling cost is 660,983.783805 JPY for SUNNY and
698,598.628643 JPY for RAIN. The RAIN day-ahead candidate cost is separately
retained as 698,296.465284 JPY and must not be reported as the final Rolling
cost.
Complete raw run directories remain outside Git and require a separate durable
archive.
