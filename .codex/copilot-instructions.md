# master-course repository-wide Copilot instructions

This repository is a research-grade EV bus dispatch / charging optimization system.
Prioritize correctness, reproducibility, explicit assumptions, and small safe changes over broad refactors.

## Project priorities
- Preserve mathematical correctness, data contracts, and reproducibility.
- Prefer minimal diffs with clear rationale.
- State what is verified from code and what is inferred.
- Do not present speculative explanations as facts.

## Architecture overview
- Frontend: React + Vite + TypeScript + Zustand
- BFF: FastAPI
- Core research logic: Python in `src/`
- Data exchange is file-based through `data/seed`, `data/built`, and `outputs/`
- Keep separation between frontend, BFF, and core optimization logic

## Non-negotiable guardrails
- Never weaken or silently alter the feasibility rule:
  `arrival + turnaround + deadhead <= next departure`
- Never silently rewrite `timetable_rows`
- Preserve `operator_id` end-to-end
- Treat missing or zero `distance_km` as a surfaced issue, not something to guess away
- Do not claim a path is “exact MILP” unless the invoked solver-backed path is verified
- Do not hide fallbacks or stub adapters; call them out explicitly

## Working style
When asked to debug or change code:
1. Identify the exact call path and files involved
2. Explain the root cause before proposing edits
3. Prefer the smallest safe patch
4. Show validation steps and expected outcomes
5. Add or update focused regression tests when practical

## Optimization logic
- Be explicit about units: kW, kWh, SOC fraction, SOC energy, timestep minutes/hours
- Separate energy charges from demand charges
- Do not average time-of-use prices unless the design explicitly requires it
- Do not mix BEV-only assumptions into ICE logic or vice versa
- Surface hidden assumptions in cost, charging, PV, and deadhead calculations

## Frontend / BFF behavior
- Prefer lazy loading and shallow payloads
- Avoid loading large graph artifacts unless required
- Preserve scenario and artifact contract behavior
- Avoid shallow-load plus full-save patterns that may erase large artifacts

## Output style
For bug-fixing tasks, structure the answer as:
1. Verified call chain
2. Root cause
3. Minimal patch
4. Risks / side effects
5. Validation steps