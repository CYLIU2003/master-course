"""Session overhead is paid once per contiguous charging session."""
import gzip
import hashlib
import itertools
import json
from pathlib import Path

import pytest

from src.optimization.milp.charging_session_relaxation import add_session_time_relaxation

POLICY = {'charging_power_model': 'piecewise_soc_taper_v1', 'charge_setup_minutes': 5,
          'charge_teardown_minutes': 5, 'minimum_charge_session_minutes': 15}


@pytest.mark.parametrize('pattern', list(itertools.product((0, 1), repeat=4)))
def test_every_binary_session_is_preserved_with_correct_boundary_overhead(pattern):
    gp = pytest.importorskip('gurobipy')
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag', 0); env.start()
        with gp.Model(env=env) as model:
            slots = list(range(len(pattern)))
            on = {('bus', s): model.addVar(lb=active, ub=active) for s, active in enumerate(pattern)}
            power = {('bus', s): model.addVar(lb=0, ub=90) for s in slots}
            add_session_time_relaxation(model, gp.GRB, vehicle_id='bus', slot_indices=slots,
                charge_on=on, charge_power=power, power_limit_kw=90, timestep_h=.25, metadata=POLICY)
            model.setObjective(gp.quicksum(power.values()) * .25, gp.GRB.MAXIMIZE)
            model.optimize()
            sessions = sum(active and (s == 0 or not pattern[s-1]) for s, active in enumerate(pattern))
            expected = 90 * (sum(pattern)*.25 - sessions*10/60)
            assert model.Status == gp.GRB.OPTIMAL
            assert model.ObjVal == pytest.approx(expected)
            assert model.NumBinVars == 0


@pytest.mark.parametrize('metadata', [{}, {'charging_power_model': 'constant_power_v0'},
                                    {**POLICY, 'charge_setup_minutes': 0, 'charge_teardown_minutes': 0}])
def test_no_overhead_policy_adds_no_rows(metadata):
    assert add_session_time_relaxation(None, None, vehicle_id='bus', slot_indices=[0],
        charge_on={}, charge_power={}, power_limit_kw=90, timestep_h=.25, metadata=metadata) == 0


def test_april_rejected_vehicle_path_is_excluded_by_session_time(tmp_path):
    """Same 82-trip path passes the old LP but cannot meet exact session times."""
    gp = pytest.importorskip('gurobipy')
    fixture = Path(__file__).parent/'fixtures/stage1_april_session_local.mps.gz'
    reference = json.loads(fixture.with_suffix('').with_suffix('.json').read_text())
    compressed = fixture.read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == reference['fixture_sha256']
    native = gzip.decompress(compressed)
    assert hashlib.sha256(native).hexdigest() == reference['source_mps_sha256']
    native_path = tmp_path/'stage1_local.mps'; native_path.write_bytes(native)
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag', 0); env.start()
        with gp.read(str(native_path), env=env) as model:
            model.Params.FeasibilityTol = 1e-9
            model.Params.IntFeasTol = 1e-9
            model.Params.TimeLimit = 15
            model.optimize()
            assert model.Status == gp.GRB.OPTIMAL
            vehicle_id = reference['vehicle_id']
            slots = list(range(672))
            power = {(vehicle_id, s): model.getVarByName(f'stage1_charge_power_kw__{vehicle_id}__slot_{s}') for s in slots}
            on = {(vehicle_id, s): model.getVarByName(f'stage1_charge_available__{vehicle_id}__slot_{s}') for s in slots}
            add_session_time_relaxation(model, gp.GRB, vehicle_id=vehicle_id, slot_indices=slots,
                charge_on=on, charge_power=power, power_limit_kw=90, timestep_h=.25, metadata=POLICY)
            model.optimize()
            assert model.Status == gp.GRB.INFEASIBLE
