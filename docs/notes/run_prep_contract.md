# Run Preparation Contract

## Cache key

`(scenario_id, dataset_version, scenario_hash)`

- `scenario_id`: runtime scenario identifier
- `dataset_version`: built dataset version loaded by the runtime
- `scenario_hash`: SHA-256 digest of the serialized scenario summary, truncated to 16 chars

## Invalidation conditions

- scenario content changes -> `scenario_hash` changes -> cache miss
- built dataset version changes -> `dataset_version` changes -> cache miss
- explicit invalidation via `invalidate_scenario(scenario_id)`

## Cache behavior

- cache hit: return existing `RunPreparation` without rebuilding scoped inputs
- cache miss: resolve runtime scope, load scoped Parquet rows, write the prepared input JSON artifact, cache result
- invalid cached entry: rebuild and replace cache entry

## prepared_input artifact

- path: `outputs/prepared_inputs/<scenario_id>/<prepared_input_id>.json`
- written during run preparation before simulation/optimization job submission
- includes scenario id, dataset version, scenario hash, scoped depot ids, scoped route ids, random seed, and row counts
