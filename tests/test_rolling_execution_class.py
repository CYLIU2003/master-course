from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.run_hourly_charging_reoptimization import RollingChainRequest, rolling_solver_config
from bff.services.optimization_run.rolling_chain import execute_frontend_rolling_chain
from src.optimization.engine import OptimizationEngine
from test_daily_return_policy import daily_problem


@pytest.mark.parametrize("formal", [True, False])
def test_rolling_preserves_execution_class_and_strict_controls(formal):
    request = RollingChainRequest("s", "p", "2025-02-03", "result.json", "out",
        research_run=formal, gurobi_threads=2, time_limit_sec=17)
    config = rolling_solver_config(request)
    assert config.research_run is formal
    assert config.allow_postsolve_repair is False
    assert config.gurobi_threads == 2
    assert config.time_limit_sec == config.stage2_time_limit_sec == 17
    assert config.phase == "phase1_charging_only"


def test_formal_multiday_guard_is_not_removed():
    request = RollingChainRequest("s", "p", "2025-02-03", "result.json", "out")
    assert request.research_run is True
    with pytest.raises(ValueError, match="MULTIDAY_RESEARCH_BLOCKED"):
        OptimizationEngine().solve(daily_problem(), rolling_solver_config(request))


@pytest.mark.parametrize("formal", [True, False])
@pytest.mark.parametrize("search,focus", [("feasibility_first", 1), ("bound_first", 3)])
def test_frontend_handoff_preserves_requested_execution_class(tmp_path, formal, search, focus):
    class CapturedRequest(Exception):
        pass

    def capture(request):
        assert request.research_run is formal
        assert request.charging_search == search
        effective = rolling_solver_config(request)
        assert effective.stage2_gurobi_mip_focus == focus
        assert effective.gurobi_threads == 2
        assert effective.time_limit_sec == 17
        assert effective.allow_postsolve_repair is False
        raise CapturedRequest

    problem = SimpleNamespace(metadata={"service_date": "2025-02-03", "rolling_charging_search": search})
    with patch("scripts.run_hourly_charging_reoptimization.run_rolling_chain", side_effect=capture), \
         patch("bff.services.optimization_run.rolling_chain._prepare_actual_pv_execution_file", return_value=None):
        with pytest.raises(CapturedRequest):
            execute_frontend_rolling_chain(run_dir=tmp_path, problem=problem, scenario_id="s",
                prepared_input_id="p", service_id="WEEKDAY", depot_id="DEPOT",
                execution_minutes=60, time_limit_sec=17, mip_gap=.01, random_seed=42,
                gurobi_threads=2, research_run=formal)


def test_rolling_search_default_and_unknown_values():
    request = RollingChainRequest("s", "p", "2025-02-03", "result.json", "out")
    assert rolling_solver_config(request).stage2_gurobi_mip_focus == 1
    from dataclasses import replace
    request = replace(request, charging_search="bound_frist")
    with pytest.raises(ValueError, match="Unknown rolling charging search"):
        rolling_solver_config(request)


def test_search_changes_only_native_focus_and_leaves_day_ahead_default():
    from dataclasses import asdict, replace
    from src.optimization.common.problem import OptimizationConfig
    from src.optimization.milp.solver_adapter import _configure_stage2_numerics

    request = RollingChainRequest("s", "p", "2025-02-03", "result.json", "out")
    baseline = rolling_solver_config(request)
    candidate = rolling_solver_config(replace(request, charging_search="bound_first"))
    assert {k for k, v in asdict(baseline).items() if asdict(candidate)[k] != v} == {"stage2_gurobi_mip_focus"}
    parameters = {}
    model = SimpleNamespace(setParam=lambda name, value: parameters.update({name: value}))
    returned = _configure_stage2_numerics(model, candidate)
    assert returned == parameters and parameters["MIPFocus"] == 3
    assert OptimizationConfig().stage2_gurobi_mip_focus == 1
