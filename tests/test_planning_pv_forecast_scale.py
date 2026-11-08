"""Planning-only PV forecast margin (pillar A, 2026-11-08)."""
from dataclasses import replace

import pytest

from src.optimization.common.planning_pv import apply_planning_pv_forecast_scale
from src.optimization.common.problem import PVSlot
from test_multiday_rolling_contract import _two_day_problem


def _problem_with_pv():
    problem = _two_day_problem()
    asset = problem.depot_energy_assets["DEPOT"]
    profile = tuple(float(i % 4) for i in range(len(asset.pv_generation_kwh_by_slot)))
    asset = replace(asset, pv_generation_kwh_by_slot=profile, available_pv_surplus_kwh_by_slot=profile)
    slots = tuple(PVSlot(slot_index=i, pv_available_kw=4.0 * v) for i, v in enumerate(profile))
    return replace(problem, depot_energy_assets={"DEPOT": asset}, pv_slots=slots)


def test_scale_multiplies_only_the_forecast_the_optimizer_reads():
    problem = _problem_with_pv()
    scaled = apply_planning_pv_forecast_scale(problem, 0.5)
    before, after = problem.depot_energy_assets["DEPOT"], scaled.depot_energy_assets["DEPOT"]
    assert after.pv_generation_kwh_by_slot == tuple(v * 0.5 for v in before.pv_generation_kwh_by_slot)
    assert after.available_pv_surplus_kwh_by_slot == tuple(v * 0.5 for v in before.available_pv_surplus_kwh_by_slot)
    assert [s.pv_available_kw for s in scaled.pv_slots] == [s.pv_available_kw * 0.5 for s in problem.pv_slots]
    assert after.pv_capacity_kw == before.pv_capacity_kw
    assert after.bess_initial_soc_kwh == before.bess_initial_soc_kwh
    assert scaled.metadata["planning_pv_forecast_scale"] == 0.5
    # The input problem is not mutated.
    assert problem.depot_energy_assets["DEPOT"] is before
    assert "planning_pv_forecast_scale" not in (problem.metadata or {})


def test_scale_one_is_the_unchanged_forecast_and_is_recorded():
    problem = _problem_with_pv()
    same = apply_planning_pv_forecast_scale(problem, 1.0)
    assert same.depot_energy_assets == problem.depot_energy_assets
    assert same.pv_slots == problem.pv_slots
    assert same.metadata["planning_pv_forecast_scale"] == 1.0


@pytest.mark.parametrize("bad", [0, 0.0, -0.1, 1.01, float("nan"), True, "0.5", None])
def test_scale_outside_zero_one_is_rejected(bad):
    with pytest.raises(ValueError):
        apply_planning_pv_forecast_scale(_problem_with_pv(), bad)


def test_request_field_defaults_to_one_and_is_bounded():
    from pydantic import ValidationError
    from bff.routers.optimization import RunOptimizationBody
    assert RunOptimizationBody.model_fields["planning_pv_forecast_scale"].default == 1.0
    with pytest.raises(ValidationError):
        RunOptimizationBody.model_validate({"planning_pv_forecast_scale": 0})
