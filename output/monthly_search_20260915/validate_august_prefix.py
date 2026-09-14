"""Validate one saved diagnostic prefix; never validate it as a whole week."""
from pathlib import Path
import hashlib
import json
import pickle
import sys

FROZEN = Path("C:/master-course-worktrees/shibu21-23-monthly-search-20260915")
sys.path.insert(0, str(FROZEN))
from src.optimization.common.result import ResultSerializer
from src.optimization.common.problem import OptimizationEngineResult, OptimizationMode
from src.optimization.rolling.pv_execution import execute_pv_prefix
from src.optimization.rolling.day_ahead_hourly import build_next_execution_state

OUT = Path(__file__).resolve().parent / "august_full_replay"
CASE = FROZEN / "output/monthly_search_campaign_20260915/cases/2025-08-04/diagnostic/2025-08-04"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    # Locally generated diagnostic pickle; verify its recorded identity first.
    protocol = read(OUT / "prefix_validation_inputs.json")
    for name, digest in protocol.items():
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == digest
    with (OUT / "rolling_problem.pkl").open("rb") as stream:
        problem, config = pickle.load(stream)
    state = read(CASE / "rolling_hourly_chain/hour_048/initial_execution_state.json")
    raw = read(OUT / "method_0_result.json")
    plan = ResultSerializer.deserialize_plan(problem, raw)
    result = OptimizationEngineResult(mode=OptimizationMode.MILP, solver_status=raw["solver_status"],
        objective_value=raw["objective_value"], plan=plan, feasible=raw["feasible"],
        cost_breakdown=raw["cost_breakdown"], solver_metadata=raw["solver_metadata"])
    actual = read(CASE / "pv_actuals_for_execution.json")["depot_profiles"]
    prefix = {depot: {slot: float(values[slot]) for slot in range(192, 196)} for depot, values in actual.items()}
    step, result, audit = execute_pv_prefix(problem, result, actual_pv_by_depot_slot=prefix,
        actual_bess_soc_kwh=state["actual_bess_soc_kwh"], start_slot=192, stop_slot=196)
    following = build_next_execution_state(step, result, current_min=2880, execution_minutes=60,
        prior_vehicle_fuel_l=state["actual_vehicle_fuel_l"], prior_on_peak_kw_by_depot=state["observed_on_peak_kw_by_depot"],
        prior_off_peak_kw_by_depot=state["observed_off_peak_kw_by_depot"])
    report = {"status": "PREFIX_ACCEPTED", "scope": "One actual-PV hour48 execution prefix; not whole-week physical validation.",
        "prior_whole_week_validation": "INAPPLICABLE_TO_TRUNCATED_ROLLING_CHARGING_PLAN",
        "result_sha256": protocol["method_0_result.json"], "next_state": following.to_dict(), "pv_execution_audit": audit}
    (OUT / "method_0_prefix_validation_reproduced.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report["status"])


if __name__ == "__main__":
    main()
