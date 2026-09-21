"""Real solver regressions for the April rolling terminal boundary."""
from pathlib import Path
import gzip
import hashlib
import json

import pytest

from src.optimization.common.problem import OptimizationConfig
from src.optimization.milp.solver_adapter import (
    _configure_stage2_numerics,
    _gurobi_numeric_diagnostics,
    ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,
)

FIXTURE = Path(__file__).parent / "fixtures/stage2_exact_terminal_boundary.ilp"


@pytest.mark.parametrize("initial_soc_increase,expected_feasible", [(0.0, True), (1.0, False)])
@pytest.mark.parametrize("rolling", [False, True])
@pytest.mark.parametrize("presolve", [0, 2])
def test_exact_boundary_is_solved_without_accepting_real_soc_surplus(
    initial_soc_increase, expected_feasible, rolling, presolve,
):
    gp = pytest.importorskip("gurobipy")
    with gp.Env(empty=True) as env:
        env.setParam("OutputFlag", 0)
        env.start()
        with gp.read(str(FIXTURE), env=env) as model:
            config = OptimizationConfig(rolling_horizon_policy=ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT if rolling else "",
                                        stage2_gurobi_presolve=presolve)
            _configure_stage2_numerics(model, config)
            model.Params.TimeLimit = 10
            model.Params.Threads = 2
            model.Params.DualReductions = 0
            initial = next(c for c in model.getConstrs() if c.ConstrName.startswith("soc_initial__"))
            initial.RHS += initial_soc_increase
            model.optimize()
            assert model.Params.FeasibilityTol == 1.0e-9
            assert model.Params.IntFeasTol == 1.0e-9
            assert model.Params.Presolve == presolve
            assert model.Params.Aggregate == 0
            assert model.Params.MIPFocus == 1
            assert model.Params.Method == (0 if rolling else 1)
            if expected_feasible:
                assert model.Status == gp.GRB.OPTIMAL
                assert model.ConstrVio <= 1.0e-9
                assert model.BoundVio <= 1.0e-9
                assert model.IntVio <= 1.0e-9
                quality = _gurobi_numeric_diagnostics(model)
                for key in (
                    "maximum_constraint_violation",
                    "maximum_bound_violation",
                    "maximum_integrality_violation",
                ):
                    assert quality[key] is not None
                    assert quality[key] <= 1.0e-9
            else:
                assert model.Status == gp.GRB.INFEASIBLE
                assert model.SolCount == 0


@pytest.mark.parametrize('value', [True, '2', -1, 3, 2.0])
def test_rejects_undeclared_or_invalid_presolve_value(value):
    with pytest.raises(ValueError, match='stage2_gurobi_presolve'):
        _configure_stage2_numerics(None, OptimizationConfig(stage2_gurobi_presolve=value))


def test_march_native_model_preserves_replayed_soc_without_presolve(tmp_path):
    """The original 64-slot model accumulated 2.185e-6 kWh after presolve."""
    gp = pytest.importorskip("gurobipy")
    fixture = FIXTURE.parent / "stage2_march_terminal_replay.mps.gz"
    reference = json.loads(fixture.with_suffix("").with_suffix(".json").read_text())
    compressed = fixture.read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == reference["fixture_sha256"]
    native_bytes = gzip.decompress(compressed)
    assert hashlib.sha256(native_bytes).hexdigest() == reference["source_mps_sha256"]
    native_path = tmp_path / "native.mps"
    native_path.write_bytes(native_bytes)
    with gp.Env(empty=True) as env:
        env.setParam("OutputFlag", 0)
        env.start()
        with gp.read(str(native_path), env=env) as model:
            _configure_stage2_numerics(model, OptimizationConfig(rolling_horizon_policy=ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT))
            assert model.Params.Aggregate == 0
            assert model.Params.Presolve == 0
            assert model.Params.MIPFocus == 1
            assert model.Params.Method == 0
            model.Params.Seed = 42
            model.Params.Threads = 12
            model.Params.MIPGap = 0.1
            model.Params.TimeLimit = 15
            model.optimize()
            assert model.SolCount > 0
            quality = _gurobi_numeric_diagnostics(model)
            assert quality["maximum_constraint_violation"] <= 1.0e-9
            vehicle_id = reference["vehicle_id"]
            soc = reference["initial_soc_kwh"]
            for slot, load in reference["slot_loads_kwh"].items():
                source_energy = sum(
                    model.getVarByName(f"{source}_{vehicle_id}_{slot}").X
                    for source in ("g2v", "pv2v", "bess2v")
                )
                soc += source_energy * reference["charge_efficiency"] - load
            assert soc >= reference["terminal_target_kwh"] - 1.0e-9


def test_auxiliary_march_predecessor_does_not_poison_next_soc_boundary(tmp_path):
    """A saved 68-slot model must supply the next hour's strict SOC floor."""
    gp=pytest.importorskip('gurobipy')
    fixture=FIXTURE.parent/'stage2_march_auxiliary_predecessor.mps.gz'
    reference=json.loads(fixture.with_suffix('').with_suffix('.json').read_text(encoding='utf-8'))
    compressed=fixture.read_bytes()
    assert hashlib.sha256(compressed).hexdigest()==reference['fixture_sha256']
    native=gzip.decompress(compressed)
    assert hashlib.sha256(native).hexdigest()==reference['source_mps_sha256']
    path=tmp_path/'march_predecessor.mps';path.write_bytes(native)
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag',0);env.start()
        with gp.read(str(path),env=env) as model:
            _configure_stage2_numerics(model,OptimizationConfig(
                rolling_horizon_policy=ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,stage2_gurobi_presolve=0))
            model.Params.TimeLimit=15;model.Params.Threads=4;model.Params.Seed=42;model.Params.MIPGap=.01
            model.optimize()
            assert model.SolCount>0
            assert model.ConstrVio<=1e-9 and model.BoundVio<=1e-9
            next_soc=model.getVarByName(f"soc_{reference['vehicle_id']}_{reference['next_boundary_slot']}").X
            assert next_soc>=reference['next_initial_min_kwh']-1e-9
