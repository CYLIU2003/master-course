# AGENTS.md

### AI Agent 八荣八耻

- 以瞎猜接口为耻，以认真查询为荣。
- 以模糊执行为耻，以寻求确认为荣。
- 以臆想业务为耻，以人类确认为荣。
- 以创造接口为耻，以复用现有为荣。
- 以跳过验证为耻，以主动测试为荣。
- 以破坏架构为耻，以遵循规范为荣。
- 以假装理解为耻，以诚实无知为荣。
- 以盲目修改为耻，以谨慎重构为荣。

## Repository purpose

This repository is a research-grade EV-bus dispatch, charging, PV, and BESS
optimization system. Correctness, reproducibility, and honest claim scope take
priority over convenience or attractive output.

## Non-negotiable research guardrails

- Never weaken or bypass
  `arrival + turnaround + deadhead <= next departure`.
- Never silently rewrite, filter, regenerate, or re-derive `timetable_rows`.
- Never drop, invent, or replace `operator_id`; formal runs require zero
  `UNKNOWN` operators.
- Never accept missing, zero, or invented route/trip distance as valid formal
  input.
- Never claim exactness merely because Gurobi reports `OPTIMAL`. A formal
  full-network claim requires zero successor pruning. A Phase 3 two-stage
  result is not an integrated global total-cost optimum.
- Never hide fallback, post-solve repair, an infeasible Stage 2, a time-limit
  incumbent, or a failed acceptance check.
- Never convert physical quantities such as fuel liters, SOC, distance, or
  energy to force monetary totals to reconcile.
- Never treat inferred vehicle-level power-source allocation as solver-native
  provenance. Depot/time source flows and proportional vehicle allocation are
  different evidence levels.
- Never bypass scenario, prepared-input, calendar, fleet, provenance, rolling,
  physical validation, or accounting contracts.
- Never mix frontend concerns directly into `src/` optimization semantics.

## Formal research-run contract

- Formal frontend runs require a clean worktree, a non-empty Git SHA, and the
  same SHA/dirty state before and after the solve.
- The prepared available fleet must contain exactly 35 BEVs and 26 ICE buses,
  with unique non-empty vehicle IDs, known vehicle types, and no unavailable
  records in the selected formal inventory.
- Formal Phase 3 runs use the complete feasible successor network. Pruned
  8/16/32-successor cases are explicitly heuristic sensitivity cases.
- Fallback and post-solve repair are forbidden.
- Day-ahead feasibility, 24/24 accepted hourly rolling, physical-schedule
  validation, research acceptance, accounting eligibility, and optimality are
  separate gates. Do not make one imply another.
- `rolling_hourly_chain/executed_day_accounting.json` is the unique final cost
  source after an accepted rolling chain. JSON, Markdown, summary, Excel, and
  the canonical ledger must reconcile to it within `1e-6 JPY`.
- A high/low-PV counterfactual must hold service date, timetable, fleet,
  initial SOC, chargers, BESS, tariff, seed, threads, time limits, and solver
  controls fixed. Only the separately hashed PV curve may differ.
- A run that misses the predeclared gap remains a physically feasible
  candidate when physical gates pass; it is not an optimality result.
- If any formal gate fails, retain diagnostic numbers but label them
  `DIAGNOSTIC`, `NOT USED FOR RESEARCH CONCLUSIONS`, and list every blocking
  reason.

## Required working procedure

1. Trace the reachable path from the user-facing entrypoint to the actual
   solver and reporting finalizer. Do not modify dead or legacy code as a
   substitute.
2. Separate verified facts from inference.
3. Use the smallest safe change and preserve dispatch/timetable/operator
   contracts.
4. For changes to formulas, costs, constraints, units, or acceptance, document
   the mathematical and comparability effects.
5. Add focused regression tests and run the relevant integration/full suite.
6. Update `README.md`, `DEVELOPMENT_NOTES.md`, and the current blocker document
   whenever behavior or claim scope changes.

## Repository and experiment discipline

- Make small, logically scoped commits.
- Create a research release branch or release-candidate tag before formal
  execution.
- Start formal experiments only from a clean frozen commit.
- Do not modify code after an experiment begins.
- Never reuse pre-change outputs after any code or mathematical-model change.
- Do not relabel an older SHA's results as evidence for the current HEAD.
- Preserve user work and unrelated dirty changes; never use destructive Git
  cleanup without explicit authorization.

## Review completion

P0/P1 issues, required tests, documentation, independent review, and a fresh
clean-commit formal run must all pass before `LGTM`, `READY`, or “model
complete” is reported.
