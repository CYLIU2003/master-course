---
applyTo: "src/**/*.py,tests/**/*.py"
---

Focus on mathematical and operational correctness.

## Rules
- Do not change objective semantics, feasibility constraints, or dispatch scoring logic unless explicitly requested
- When touching charging, PV, battery, or cost logic, verify units and timestep interpretation
- Separate the following concepts clearly:
  - power (kW)
  - energy (kWh)
  - SOC fraction
  - SOC energy
  - instantaneous peak demand
  - accumulated energy charge
- If a solver path contains fallback behavior, stub adapters, or partial implementations, surface that explicitly
- If a route or trip distance is missing or zero, treat it as a correctness issue to report
- Prefer adding regression tests for any bug fix

## Required analysis style
Before proposing edits, identify:
- entrypoint function
- config flags that affect behavior
- actual solver path invoked
- data fields used by the logic
- whether the issue is verified or inferred