"""Real solver regressions for the April rolling terminal boundary."""
from pathlib import Path

import pytest

from src.optimization.common.problem import OptimizationConfig
from src.optimization.milp.solver_adapter import _configure_stage2_numerics

FIXTURE = Path(__file__).parent / "fixtures/stage2_exact_terminal_boundary.ilp"


@pytest.mark.parametrize("initial_soc_increase,expected_feasible", [(0.0, True), (1.0, False)])
def test_exact_boundary_is_solved_without_accepting_real_soc_surplus(
    initial_soc_increase, expected_feasible,
):
    gp = pytest.importorskip("gurobipy")
    with gp.Env(empty=True) as env:
        env.setParam("OutputFlag", 0)
        env.start()
        with gp.read(str(FIXTURE), env=env) as model:
            _configure_stage2_numerics(model, OptimizationConfig())
            model.Params.TimeLimit = 10
            model.Params.Threads = 2
            model.Params.DualReductions = 0
            initial = next(c for c in model.getConstrs() if c.ConstrName.startswith("soc_initial__"))
            initial.RHS += initial_soc_increase
            model.optimize()
            assert model.Params.FeasibilityTol == 1.0e-9
            assert model.Params.IntFeasTol == 1.0e-9
            if expected_feasible:
                assert model.Status == gp.GRB.OPTIMAL
                assert model.ConstrVio <= 1.0e-9
                assert model.BoundVio <= 1.0e-9
                assert model.IntVio <= 1.0e-9
            else:
                assert model.Status == gp.GRB.INFEASIBLE
                assert model.SolCount == 0
