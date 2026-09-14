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
)

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
            assert model.Params.Presolve == 0
            assert model.Params.Aggregate == 0
            assert model.Params.MIPFocus == 1
            assert model.Params.Method == 1
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
            _configure_stage2_numerics(model, OptimizationConfig())
            assert model.Params.Aggregate == 0
            assert model.Params.Presolve == 0
            assert model.Params.MIPFocus == 1
            assert model.Params.Method == 1
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
