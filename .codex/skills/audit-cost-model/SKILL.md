---
name: audit-cost-model
description: Use when: reviewing or changing charging cost, PV, battery, SOC, TOU pricing, or demand charge logic.
---

# audit-cost-model

## Goal
Audit cost and energy logic for unit consistency and mathematical correctness.

## Checklist
- Verify whether each timeseries is kW or kWh
- Verify timestep conversion
- Separate energy charge from demand charge
- Check TOU price matching by time bin
- Check demand charge as peak demand, not summed demand
- Check SOC semantics and battery balance equations
- Check deadhead energy basis
- Flag hidden assumptions explicitly

## Output format
1. Verified formulas / logic path
2. Unit consistency issues
3. Modeling issues
4. Minimal corrections
5. Validation tests