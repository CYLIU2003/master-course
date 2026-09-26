from types import SimpleNamespace

import pytest

from src.gurobi_session import dispose_model, managed_gurobi_session, track_model
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


@pytest.mark.parametrize("charging_fails", [False, True])
def test_fixed_assignment_handoff_frees_native_memory_but_keeps_license(charging_fails):
    events = []
    allocated = [14]

    class AssignmentModel:
        disposed = False

        @property
        def Runtime(self):
            assert not self.disposed
            return 1800.71

        def dispose(self):
            assert not self.disposed, "must not be disposed twice at session close"
            self.disposed = True
            allocated[0] -= 14
            events.append("assignment_disposed")

    env = SimpleNamespace(dispose=lambda: events.append("env_disposed"))
    problem, config, plan = object(), object(), object()
    evidence = dict(stage1_status="time_limit", stage1_gap=1.0, stage1_bound=0.0,
                    stage1_objective_value=4220860.91, slots_per_day=96)
    adapter = GurobiMILPAdapter()

    with managed_gurobi_session(lambda: None, lambda started: events.append("grant_released")) as session:
        session.env, session.admitted, session.started = env, True, True
        assignment = track_model(AssignmentModel())
        other = track_model(SimpleNamespace(dispose=lambda: events.append("other_disposed")))

        def charging(p, c, saved_plan, **kwargs):
            assert allocated[0] + 2 <= 14, "charging must have its native memory available"
            assert session.env is env and session.started and session.admitted
            assert session.models == [other]
            assert events == ["assignment_disposed"]
            assert (p, c, saved_plan) == (problem, config, plan)
            assert kwargs == {**evidence, "stage1_runtime_sec": 1800.71}
            if charging_fails:
                raise RuntimeError("charging failed")
            return "outcome", saved_plan

        adapter._solve_thesis_stage2_charging_dispatch = charging
        if charging_fails:
            with pytest.raises(RuntimeError, match="charging failed"):
                adapter._solve_charging_after_stage1_release(assignment, problem, config, plan, **evidence)
        else:
            assert adapter._solve_charging_after_stage1_release(
                assignment, problem, config, plan, **evidence) == ("outcome", plan)
    assert events == ["assignment_disposed", "other_disposed", "env_disposed", "grant_released"]


def test_disposal_failure_retains_model_for_cleanup(monkeypatch):
    import src.gurobi_session as module

    def fail():
        raise RuntimeError("dispose failed")

    model = SimpleNamespace(dispose=fail)
    session = SimpleNamespace(models=[model])
    monkeypatch.setattr(module, "current_session", lambda: session)
    with pytest.raises(RuntimeError, match="dispose failed"):
        dispose_model(model)
    assert session.models == [model]
