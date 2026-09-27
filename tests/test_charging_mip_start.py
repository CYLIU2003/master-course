from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.optimization.common.problem import ChargingSlot, OptimizationConfig
from src.optimization.milp.charging_mip_start import apply_charging_mip_start
from scripts.run_hourly_charging_reoptimization import (
    RollingChainRequest, rolling_solver_config, run_rolling_chain,
)


class StartOnlyModel:
    """Any constraint/parameter/model operation would fail this stub."""
    def __init__(self):
        self.calls = []

    def setAttr(self, attribute, variables, values):
        assert attribute == "Start"
        self.calls.append((list(variables), list(values)))
        for var, value in zip(variables, values, strict=True):
            var.Start = value


def inputs():
    variable = lambda: SimpleNamespace(LB=0, UB=1, Start=None)
    return {"model": StartOnlyModel(), "policy": "fixed_assignment_binary", "warm_start": True,
            "charging_slots": (ChargingSlot("v", 100, "a", charge_kw=10),),
            "charge_on_vars": {("v", slot): variable() for slot in (100, 101)},
            "charger_vars": {("v", charger, slot): variable() for slot in (100, 101) for charger in ("a", "b")},
            "window_start_slot": 100, "connected_chargers": {}, "active_session_vehicle_ids": ()}


def test_binary_proposal_keeps_bounds_and_never_claims_native_acceptance():
    args = inputs()
    audit = apply_charging_mip_start(**args)
    assert audit["status"] == "SUBMITTED"
    assert audit["solver_acceptance"] == "NOT_OBSERVED"
    assert audit["submitted_variables"] == 6
    assert args["charge_on_vars"][("v", 100)].Start == 1
    assert args["charge_on_vars"][("v", 101)].Start == 0
    assert [v.Start for v in args["charger_vars"].values()] == [1, 0, 0, 0]
    assert all((v.LB, v.UB) == (0, 1) for v in args["charger_vars"].values())


def test_sources_aggregate_before_positive_power_threshold():
    args = inputs()
    args["charging_slots"] = tuple(ChargingSlot("v", 100, "a", charge_kw=0.5e-6, energy_source=s)
                                   for s in ("pv", "grid", "bess"))
    assert apply_charging_mip_start(**args)["source_positive_slots"] == 1
    assert args["charge_on_vars"][("v", 100)].Start == 1


def test_support_hash_is_independent_of_source_split_and_order():
    a, b = inputs(), inputs()
    b["charging_slots"] = (ChargingSlot("v", 100, "a", charge_kw=4, energy_source="grid"),
                            ChargingSlot("v", 100, "a", charge_kw=6, energy_source="pv"))
    assert apply_charging_mip_start(**a)["source_support_sha256"] == apply_charging_mip_start(**b)["source_support_sha256"]


def test_absolute_slots_are_not_shifted_to_window_local_indices():
    args = inputs()
    args["charging_slots"] = (ChargingSlot("v", 0, "bad", charge_kw=10),
                              ChargingSlot("v", 100, "b", charge_kw=10))
    apply_charging_mip_start(**args)
    assert args["charger_vars"][("v", "b", 100)].Start == 1


def test_conflicting_ongoing_connection_is_unspecified_not_rewritten():
    args = inputs()
    args.update(connected_chargers={"v": "b"}, active_session_vehicle_ids=("v",))
    audit = apply_charging_mip_start(**args)
    assert audit["omitted_connection_slots"] == 1
    assert args["charge_on_vars"][("v", 100)].Start is None
    assert args["charger_vars"][("v", "a", 100)].Start is None
    assert args["charger_vars"][("v", "b", 100)].Start is None
    assert args["charge_on_vars"][("v", 101)].Start == 0


def test_boundary_comes_from_window_not_first_available_variable():
    args = inputs()
    args.update(window_start_slot=99, connected_chargers={"v": "b"}, active_session_vehicle_ids=("v",))
    assert apply_charging_mip_start(**args)["omitted_connection_slots"] == 0
    assert args["charger_vars"][("v", "a", 100)].Start == 1


def test_all_boundary_proposals_omitted_are_not_reported_as_submitted():
    args = inputs()
    args["charge_on_vars"] = {k: v for k, v in args["charge_on_vars"].items() if k[1] == 100}
    args["charger_vars"] = {k: v for k, v in args["charger_vars"].items() if k[2] == 100}
    args.update(connected_chargers={"v": "b"}, active_session_vehicle_ids=("v",))
    audit = apply_charging_mip_start(**args)
    assert audit["status"] == "NOT_APPLIED"
    assert audit["submitted_variables"] == 0
    assert args["model"].calls == []


@pytest.mark.parametrize("field,value", [("charge_kw", float("nan")), ("charge_kw", -1),
                                         ("discharge_kw", 10), ("charger_id", "absent")])
def test_bad_source_does_not_partially_write_starts(field, value):
    args = inputs()
    args["charging_slots"] = (replace(args["charging_slots"][0], **{field: value}),)
    assert apply_charging_mip_start(**args)["status"] == "NOT_APPLIED"
    assert args["model"].calls == []


def test_two_physical_chargers_in_one_slot_are_rejected():
    args = inputs()
    args["charging_slots"] += (ChargingSlot("v", 100, "b", charge_kw=10),)
    assert apply_charging_mip_start(**args)["reason"] == "multiple_source_chargers_in_slot"
    assert args["model"].calls == []


@pytest.mark.parametrize("changes", [{"policy": "none"}, {"warm_start": False}, {"charging_slots": ()}])
def test_disabled_or_empty_has_no_native_writes(changes):
    args = {**inputs(), **changes}
    assert apply_charging_mip_start(**args)["status"] == "NOT_APPLIED"
    assert args["model"].calls == []


def test_unknown_policy_rejected_before_license_probe():
    request = RollingChainRequest("s", "p", "2025-01-06", "r", "o", stage2_charging_start_policy="typo")
    with patch("scripts.run_hourly_charging_reoptimization.is_gurobi_available", side_effect=AssertionError("license probe")):
        with pytest.raises(ValueError, match="Unsupported"):
            run_rolling_chain(request)


def test_request_preserves_default_and_opt_in_without_relaxing_controls():
    request = RollingChainRequest("s", "p", "2025-01-06", "r", "o")
    assert OptimizationConfig().stage2_charging_start_policy == "none"
    assert rolling_solver_config(request).stage2_charging_start_policy == "none"
    control = rolling_solver_config(request)
    candidate = rolling_solver_config(replace(request, stage2_charging_start_policy="fixed_assignment_binary"))
    assert replace(candidate, stage2_charging_start_policy="none") == control
    assert candidate.allow_postsolve_repair is False


def test_real_rolling_entry_preserves_start_policy_and_measured_connection():
    from src.optimization.rolling.reoptimizer import RollingReoptimizer
    from test_multiday_rolling_contract import _two_day_problem, _fixed_plan

    problem = _two_day_problem()
    charger = problem.chargers[0].charger_id
    plan = replace(_fixed_plan(problem), charging_slots=(ChargingSlot("bev-1", 0, charger, charge_kw=10),))
    rolling = RollingReoptimizer()
    rolling._engine = SimpleNamespace(solve=lambda problem, config: config)
    original = OptimizationConfig(stage2_charging_start_policy="fixed_assignment_binary")
    effective = rolling.reoptimize_charging_hour(problem, plan, original, 0,
        connected_charger_by_vehicle={"bev-1": charger}, active_charge_session_vehicle_ids=("bev-1",))
    assert effective.stage2_charging_start_policy == "fixed_assignment_binary"
    assert effective.rolling_connected_charger_by_vehicle == {"bev-1": charger}
    assert effective.rolling_active_charge_session_vehicle_ids == ("bev-1",)
    assert effective.fixed_assignment is plan
    assert original.rolling_connected_charger_by_vehicle == {}
