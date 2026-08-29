# Fresh SUNNY/RAIN public-path rerun at `bb0c005`

Verdict: **PASS_NORMAL_PATH_CONFIRMATION; thesis release remains BLOCKED.**

This is the compact Git-tracked review bundle for two Fresh Prepare runs from
clean tag `thesis-weather-rerun-bb0c005` / execution SHA
`bb0c0050883a91dd86a9e8813ae88d4b6d8c361d`. The BFF was started from that
SHA and both cases used the public Prepare and run-optimization endpoints.

| metric | SUNNY | RAIN |
|---|---:|---:|
| served trips | 264/264 | 264/264 |
| used BEV / ICE | 28 / 4 | 21 / 11 |
| BEV / ICE trips | 199 / 65 | 91 / 173 |
| evaluated feasible candidates | 22/22 | 22/22 |
| day-ahead selected cost (JPY) | 660,983.783805 | 698,296.465284 |
| authoritative executed-day cost (JPY) | 660,983.783805 | 698,598.628643 |
| Stage-1 certified gap | 9.5213476% | 1.6563581% |
| physical validation | PASS | PASS |
| Rolling | 24/24 accepted | 24/24 accepted |
| accounting | OK | OK |

The selected physical assignment hashes are different and exactly reproduce
the prior fixed-dispatch Case-A winners. The full input contract confirms that
timetable, fleet, chargers, BESS/PV asset controls, tariff, objective, and
solver controls match. The differing hashes are limited to the authoritative
PV profile, derived canonical/PV hashes, and scenario-specific prepared
snapshots.

Start review with [`result_summary.json`](result_summary.json), then inspect
[`confirmation_manifest.json`](confirmation_manifest.json),
[`normal_confirmation_input_contract.json`](normal_confirmation_input_contract.json),
and each scenario's `confirmation_gate.json`. The finalization manifest hashes
31 raw artifacts, including the full solver and candidate files that are too
large for this compact subset. Each scenario therefore includes a complete
`selected_candidate.json` plus a bounded `solver_metrics.json`, both tied to
their raw source artifact SHA-256. `artifact_hashes.json` verifies every file
that is actually published here.

This evidence supports a reproducible, physically feasible Phase-3 two-stage
comparison for these two fixed scenarios. It does **not** establish an
integrated global optimum, a 1%-optimal solution, a general weather benefit,
or thesis-release readiness. RAIN is the established low-PV counterfactual on
the same 2025-08-05 WEEKDAY service, not an observed Sunday timetable.
