# AGENTS.md

## Purpose
This repository is a research-grade EV bus dispatch / charging scheduling and optimization system.
Your job is to help safely debug, extend, and explain the system without breaking research validity, data contracts, or reproducibility.

## Core mindset
- Correctness over cleverness
- Reproducibility over convenience
- Minimal safe diffs over broad rewrites
- Verified facts over speculation
- Transparent limitations over overstated claims

## Absolute guardrails
- Never weaken or silently alter the dispatch feasibility condition:
  `arrival + turnaround + deadhead <= next departure`
- Never silently rewrite or re-derive `timetable_rows`
- Never drop, ignore, or invent `operator_id`
- Never claim a solver path is exact or MILP-backed unless verified from the actual invocation path
- Never gloss over fallback logic, stub adapters, or incomplete implementations
- Never silently accept zero or missing route/trip distance as valid
- Never mix frontend concerns directly into `src/` core optimization logic
- Never bypass artifact or scenario contract checks without explicitly stating it

## Standard operating procedure
For any non-trivial task, follow this order:

1. Understand the request
- Restate the technical objective internally
- Identify whether the task is about frontend, BFF, optimization core, data pipeline, or documentation

2. Trace the true execution path
- Find the user-facing entrypoint
- Follow the call chain to the implementation actually invoked
- Distinguish between reachable code and dead / legacy / unused code

3. Separate verified facts from inferences
- Mark what is directly confirmed from files, function calls, configs, tests, or logs
- Mark what is inferred from naming, structure, or likely intent

4. Minimize change scope
- Prefer the smallest patch that fixes the issue
- Do not refactor unrelated code unless explicitly asked
- If a larger cleanup is desirable, propose it separately

5. Protect research validity
- If editing formulas, costs, constraints, units, or dispatch logic, explain the mathematical effect
- If behavior changes, explain what experimental results may no longer be comparable

6. Validate explicitly
- Provide concrete validation steps
- Prefer focused tests and reproducible commands
- State what a successful result should look like

## Required answer structure for debugging
When asked to debug, answer in this format:
1. Verified call chain
2. Root cause
3. Minimal patch
4. Risks / side effects
5. Validation steps
6. Remaining uncertainty

## Domain-specific checks

### Optimization / solver tasks
Always check:
- exact run mode
- config flags and defaults
- actual solver implementation called
- fallback behavior
- whether the result is optimization or just evaluation of a baseline
- units of SOC, power, energy, timestep, and demand charge

### PV / battery / charging tasks
Always check:
- whether the data is power or energy
- timestep conversion consistency
- charging/discharging sign conventions
- energy balance
- TOU matching by time bin
- demand charge as peak kW, not simple summed kW
- whether grid charging of stationary battery is allowed or forbidden by design

### Dispatch tasks
Always check:
- trip identity fields
- route family / variant handling
- direction propagation
- depot constraints
- swap flags
- feasibility condition preservation

### Frontend tasks
Always check:
- repeated renders
- large payload loading
- store synchronization
- whether a slow path can be deferred until simulation or graph view
- whether UI edits mutate common assets or scenario overlays incorrectly

### BFF / persistence tasks
Always check:
- shallow-load vs full-save behavior
- staging directory lifecycle
- file lock risk
- artifact invalidation side effects
- API contract consistency

## Things to say explicitly when relevant
- “This is verified from the current call path”
- “This appears to be dead code / unused in the current flow”
- “This is an inference, not yet confirmed”
- “This changes the mathematical meaning of the model”
- “This preserves existing experiment comparability”
- “This may invalidate previous KPI claims”

## Preferred code change style
- Small, surgical diffs
- Clear comments only where ambiguity exists
- Preserve naming and structure unless a rename removes real ambiguity
- Add regression tests for bugs when practical
- Avoid introducing heavy abstractions without a proven need

## Preferred documentation style
- State assumptions
- State units
- State data source and transformation path
- Distinguish current implementation, intended design, and future work

## If asked to review a PR or patch
Review for:
- correctness
- hidden fallback behavior
- contract breakage
- unit inconsistency
- reproducibility risks
- accidental performance regressions
- unsupported claims in docs/comments
