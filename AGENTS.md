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
- ODPT timetable acquisition, source audit, and optimization-DB rebuild are
  explicit researcher-triggered operations. Job submission, Prepare, and solve
  must consume a verified, immutable timetable snapshot; they must not refresh
  ODPT or rebuild that snapshot. A changed snapshot requires a new experiment
  version and fresh Prepare for every compared case.
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
- Formal runs must use the exact active vehicle set derived from the
  materialized prepared scenario and the explicitly selected depot/dispatch
  scope. No global BEV/ICE count is hard-coded. Counts are derived from that
  exact set; vehicle IDs, initial state, parameters, availability exclusions,
  and the fleet-contract hash must be preserved and checked.
- Persisted unavailable/disabled/maintenance vehicles may exist, but they must
  be excluded with a recorded reason. A vehicle that was active at Prepare
  time must not silently disappear or change before execution.
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

1. For optimization behavior changes, trace the affected reachable path from
   the user-facing entrypoint to the solver and reporting finalizer. For other
   tasks, inspect only the relevant path. Do not fix dead code as a substitute.
2. Separate verified facts from inference.
3. Use the smallest safe change and preserve dispatch/timetable/operator
   contracts.
4. For changes to formulas, costs, constraints, units, or acceptance, document
   the mathematical and comparability effects.
5. For executable behavior changes, add focused regression coverage and run
   affected tests; run integration/full suites when the impact warrants them.
   For instruction or documentation changes, validate syntax, links, and rule
   consistency. Reuse checks for the same content, inputs, and environment;
   repeat only for new changes, failures, or unresolved concerns.
6. Record changes in the relevant explanation document. Update `README.md`
   when user-facing guidance changes and `DEVELOPMENT_NOTES.md` for development
   decisions. Update `docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md` only when
   research blockers or research claim scope change. Do not read or rewrite
   unrelated documents merely to satisfy a checklist.

## Task scope and skill selection

- Apply a skill when the requested deliverable matches its scope or the user
  explicitly invokes it. Generic words such as "write", "analyze", or "review"
  alone do not require unrelated skills. Load only relevant supporting files.
- In this project, `.codex/skills/<name>/SKILL.md` is the maintained source for
  project skills. Do not additionally load a same-name user-wide copy. Existing
  `.skill` archives are distribution snapshots, not active instruction sources;
  refresh them only when packaging or distributing a skill is requested.
- Resolve routine questions using available evidence and existing authorization.
  Ask only when a material ambiguity cannot be resolved by inspection, or an
  action requires authorization that has not been given. Do not ask again for
  an already authorized action; continue independent work while a question waits.
- Findings must be evidence-backed; do not invent defects to satisfy a review
  format. A review-only request authorizes findings and proposals, not edits.

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

- Code-review approval requires resolution of P0/P1 findings and the tests and
  documentation applicable to the change. CI and coverage gates apply only if
  configured and relevant; record why a check is not applicable or could not run.
  Do not enable CI or paid services merely to satisfy a review checklist.
- Report self-review and independent review separately. If independent review
  is required for a merge or release, leave that approval pending until obtained;
  do not make it a prerequisite for reporting local work and validation complete.
- Research approval (`READY` for research use or "model complete") additionally
  requires independent review and a fresh clean-commit formal run satisfying
  every applicable research gate above. Code-review `LGTM` does not imply
  research approval. Documentation-only work does not require a formal solve.
