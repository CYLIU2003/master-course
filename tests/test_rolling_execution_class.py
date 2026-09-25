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
def test_frontend_handoff_preserves_requested_execution_class(tmp_path, formal):
    class CapturedRequest(Exception):
        pass

    def capture(request):
        assert request.research_run is formal
        raise CapturedRequest

    problem = SimpleNamespace(metadata={"service_date": "2025-02-03"})
    with patch("scripts.run_hourly_charging_reoptimization.run_rolling_chain", side_effect=capture), \
         patch("bff.services.optimization_run.rolling_chain._prepare_actual_pv_execution_file", return_value=None):
        with pytest.raises(CapturedRequest):
            execute_frontend_rolling_chain(run_dir=tmp_path, problem=problem, scenario_id="s",
                prepared_input_id="p", service_id="WEEKDAY", depot_id="DEPOT",
                execution_minutes=60, time_limit_sec=17, mip_gap=.01, random_seed=42,
                gurobi_threads=2, research_run=formal)
