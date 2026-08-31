# Expected artifact inventory

Small oracle: run plan, Prepare response, prepared manifest, progress manifest, one immutable directory for each of 8/12/24 trips, command/stdout/stderr/result per directory, complete run manifest, and SHA-256 artifact manifest.

RAIN 2x2: run/profile definitions, common requests, Prepare and prepared manifests, progress/run/artifact manifests, and for each profile the request, terminal job response, effective controls, candidate evaluation, physical validation, Rolling summary/accounting, reconciliation, summary, optimization parameters, provenance, input audit, normalized profile result, and source hashes.

The package is incomplete if an expected file is absent, an unexpected mutable file is present, or any recorded hash differs.
