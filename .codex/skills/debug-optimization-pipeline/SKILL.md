---
name: debug-optimization-pipeline
description: Use when: debugging why optimization does not run, why a run mode behaves unexpectedly, or which solver path is actually invoked in the repository.
---

# debug-optimization-pipeline

## Goal
Determine the real execution path of an optimization request and identify the smallest safe fix.

## Steps
1. Start from the user-facing entrypoint
2. Trace frontend -> BFF -> service -> core solver path
3. Identify the actual run mode and implementation invoked
4. Detect fallbacks, stub adapters, dead code, or silent behavior changes
5. Produce:
   - verified call chain
   - root cause
   - minimal patch
   - validation steps

## Required checks
- config flags and defaults
- actual solver path versus intended solver path
- artifact / scenario readiness assumptions
- whether the result is optimized, baseline-evaluated, or fallback-generated

## Output format
1. Verified call chain
2. Root cause
3. Minimal patch
4. Risks
5. Validation