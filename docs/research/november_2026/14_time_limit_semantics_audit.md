# Time-limit semantics audit

Verdict: `C. SHARED_MIXED_BUDGET`.

`RunOptimizationBody.time_limit_seconds` is mapped directly to
`OptimizationConfig.time_limit_sec`. In Phase 3, the MILP adapter creates one
monotonic deadline from that value. Stage 1 and every candidate Stage 2 draw
from this shared day-ahead deadline; the explicit Stage 1 and Stage 2 values
are per-stage caps inside it. If neither stage cap is supplied, each defaults
to half of the shared value.

This request field does **not** include the 24 Rolling solves. The frontend
calls Rolling after the day-ahead result and gives each charging-only step the
explicit Stage 2 limit, or 30 seconds when no override is supplied. It also
does not control HTTP request timeouts, job polling timeout, process lifetime,
or the signoff wall budget. Those are orchestration controls and remain
separate from the optimization request.

The frozen RAIN reference records 585 seconds total, 435 seconds Stage 1, and
30 seconds Stage 2. Therefore v2's BASE value 2115 did not reproduce the
reference: it incorrectly added candidate and Rolling allowances to a field
that is already the shared Phase 3 day-ahead budget. v3 restores BASE to
585/435/30. RANGE_ONLY keeps those same solver budgets. The budget factor uses
1650/1500/30 for BUDGET_ONLY and FULL_EXPANDED; the extra 120 seconds mirrors
the reference's shared-budget margin. External family wall caps are declared
only in the approval manifest and runner CLI.

The resulting matrix is a true preregistered 2x2 for the declared factors:

| Profile | Range | Shared/Stage1/Stage2 seconds |
|---|---|---|
| BASE | 22 candidates, radius 4, BEV 15--35 | 585 / 435 / 30 |
| RANGE_ONLY | 44 candidates, radius 8, BEV 5--35 | 585 / 435 / 30 |
| BUDGET_ONLY | 22 candidates, radius 4, BEV 15--35 | 1650 / 1500 / 30 |
| FULL_EXPANDED | 44 candidates, radius 8, BEV 5--35 | 1650 / 1500 / 30 |

It supports only finite-profile main effects and interaction descriptions.
It does not establish global search completeness, optimality, or a causal
effect outside these four profiles.
