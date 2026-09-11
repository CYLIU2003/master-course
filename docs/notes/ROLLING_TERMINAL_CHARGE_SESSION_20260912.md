# Rolling terminal charging-session continuity

## Follow-up on frozen cdd66532: SOC roundoff after 15 hours

The fresh winter day-ahead again passed native feasibility and independent
physical validation (447.481 seconds; Stage 1 gap 0.8464525489). Fifteen hourly
execution prefixes were persisted successfully. The next call, hour 15, raised
`Frozen terminal SOC target violates physical bounds` at forecast boundary 156.
The exact failing value was 62.8 kWh; the canonical reserve was
62.800000000000004 kWh. Their difference is 7.105427357601002e-15 kWh.
An audit of all stored reference points found 215 strict floating-point boundary
comparisons with that same maximum discrepancy; no material SOC violation was
identified. The canonical vehicle parameters match the preceding frozen input.

`effective_final_soc_target_kwh` now uses the same 1e-6 kWh numerical boundary
tolerance as `vehicle_initial_soc_kwh`. It returns the original frozen value
unchanged. Native SOC bounds, targets, cost formulas and independent physical
validation remain in place. Nonfinite targets and deviations greater than the
numeric tolerance still raise, with the vehicle, target and bounds in the error.
Six regressions cover lower/upper roundoff without clipping and genuine lower/
upper violations, NaN and infinity. The relevant SOC and session tests pass 33/33.

The exception handler previously replaced all partial progress with zero. The
failed campaign's raw `progress.json` and 15 hourly artifact directories are the
evidence for progress; its summary's zero is a reporting defect. The handler is
corrected to retain only supported progress while keeping final costs
empty and accounting/research eligibility false. This failure does not establish
168-hour acceptance, and subsequent seasons were not executed.

The corrected reporting helper recovered exactly 15 accepted hours and failed
hour 15 from the retained real artifacts. A resumed diagnostic with the SOC fix
passed hours 15 through 26, including actual-PV execution handoff and the first
service-day boundary. It does not replace a fresh campaign. After the independent
structural precheck reuse change, hours 27 through 32 also passed; see
[reuse equivalence and timing](STRICT_PRECHECK_REUSE_20260912.md).

Final combined validation: 2,197 passed / 2 existing PowerPoint evidence failures
in 95.37 seconds. The targeted cache/SOC/progress suite passed 68 tests and
independent review found zero remaining P0/P1 in these changes. JUnit is
`output/exact_depot_factor_validation/pytest-rolling-roundoff-precheck-release.xml`.
New clean-commit execution remains required before a weekly acceptance claim.

## Verified failure on frozen 2bd7cc9f

The fresh winter Prepare retained 1,704 timetable trips, the exact 60-vehicle
fleet (35 BEV / 25 ICE), zero UNKNOWN operators and zero nonpositive distances.
All 78,647,760 feasible successor candidates were retained. The native day-ahead
solve was feasible in 451.735 seconds and independent physical validation passed.
Stage 1 gap was 0.8464525489, above the declared 0.10; this is not optimality.

The first 24-hour rolling window ended at slot 96 and was INFEASIBLE.
Vehicle `d225af48-8eec-47b7-abb1-34cfe83e31f0` needed the day-ahead boundary SOC
97.245959252 kWh. Its reference charged at 60 kW in slot 95 and 90 kW in slot 96.
The IIS included the last-slot charge end and net-session-time constraints.
For a 15-minute slot, 90 kW charger and 5-minute setup/teardown, forcing both
start and end leaves at most 30 kW average, although continuing after setup
permits 60 kW. The intermediate boundary incorrectly imposed a physical end.

Evidence remains under the frozen worktree
`C:/master-course-worktrees/shibu21-23-seed-20260911/output/shibu21_23_exact_seed_campaign_20260911`.
This failed run accepted 0/168 execution prefixes; later seasons were not run.

## Reachable correction and mathematical scope

`RollingReoptimizer.reoptimize_charging_hour` derives continuation exclusively
from the fixed day-ahead forecast charging slots when the reference has positive
power on both sides of an intermediate boundary. Stage 2 fixes the last charge
active indicator to 1 and its end indicator to 0 for these continuing sessions.
It records the reference and consecutive future slot count in result metadata.
It never reads future actual PV to choose this boundary condition.

The native constraint remains
`power_kw * dt_h <= max_kw * (dt_h * on - setup_h * start - teardown_h * end)`.
If a minimum session needs slots beyond the window, the known continuing suffix
must cover the missing slots and every remaining in-window slot must stay on.
Without a continuing reference, or at the true evaluation end, the original end
and minimum-duration constraints remain. Original BEV terminal targets, taper,
chargers, SOC bounds, daily return, fuel, fleet and full-successor controls remain.

Session state follows the existing vehicle-level positive-charge convention.
The reference changes charger IDs between slots at the same depot; this change
does not introduce a charger-transfer setup model. A connector-level physical
session model would require a separate specified contract and validation.

## Validation and claim boundary

Existing daily-return and rolling regressions: 59 passed. Three new native and
reference regressions cover 15-minute end capacity, minimum-duration continuation,
positive power on both sides, suffix counting and evaluation-end restoration.
Retained-input first-window replay passed with no infeasibility reasons
(33.938 seconds wall, including construction and finalization).
This is a code regression, not a new campaign or evidence for an unfrozen SHA.
The four-hour replay passed every forecast solve and actual-PV execution-state
handoff (33.02, 32.89, 33.21, 32.98 seconds per forecast solve). Focused review
validation passed 68 tests; independent review found zero remaining P0/P1 for
this change. Full regression: 2,172 passed / 2 existing PowerPoint evidence
failures in 99.12 seconds, recorded in
`output/exact_depot_factor_validation/pytest-rolling-terminal-release.xml`.
The failure-result branch also records the boundary audit after review.
Fresh clean-commit Prepare and all four 168-hour chains remain
required. All seasonal outputs are DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS.
