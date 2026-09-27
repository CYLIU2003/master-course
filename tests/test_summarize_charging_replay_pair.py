import hashlib
import json

import pytest

from tools.research.summarize_charging_replay_pair import summarize


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def evidence(root):
    profiles = []
    for policy, seconds, objective in [("none", 20, 100), ("fixed_assignment_binary", 10, 101)]:
        directory = root / policy
        directory.mkdir()
        (directory / "model-0.mps").write_bytes(b"model")
        native = [{"mps_sha256": hashlib.sha256(b"model").hexdigest(), "Runtime": seconds,
                   "MaxMemUsed": .5, "Status": 9, "MIPGap": .02}]
        write(directory / "native-models.json", native)
        write(directory / "result.json", {"feasible": True, "objective_value": objective})
        profiles.append({"policy": policy, "native_models": native, "feasible": True,
                         "objective_value": objective, "wall_seconds": seconds + 2})
    state = {"status": "DIAGNOSTIC_COMPLETED", "profiles": profiles, "memory_budget_gib": 8,
             "git_before": {"sha": "fixed", "dirty": False}, "git_after": {"sha": "fixed", "dirty": False}}
    write(root / "state.json", state)
    write(root / "preflight.json", {})
    return state


def test_faster_but_worse_candidate_is_reported_without_adoption(tmp_path):
    evidence(tmp_path)
    report = summarize(tmp_path)
    assert report["candidate_minus_baseline_call_seconds"] == -10
    assert report["candidate_minus_baseline_window_objective"] == 1
    assert report["production_adoption"] == "NOT_AUTOMATIC_SINGLE_WINDOW_ONLY"
    assert report["independent_weekly_physical_audit"] == "NOT_PERFORMED"
    assert report["profiles"][1]["shared_environment_cumulative_peak_gb"] == .5
    assert "not proven optimal" in report["comparison_meaning"]
    assert report["profiles"][1]["native_termination_status"] == [9]


def test_incomplete_pair_is_not_summarized(tmp_path):
    state = evidence(tmp_path)
    state["status"] = "RUNNING_none"
    write(tmp_path / "state.json", state)
    with pytest.raises(ValueError, match="not complete"):
        summarize(tmp_path)


def test_model_corruption_is_rejected(tmp_path):
    evidence(tmp_path)
    (tmp_path / "none/model-0.mps").write_bytes(b"different model")
    with pytest.raises(ValueError, match="evidence changed"):
        summarize(tmp_path)


def test_summary_cannot_hide_infeasibility(tmp_path):
    evidence(tmp_path)
    write(tmp_path / "fixed_assignment_binary/result.json", {"feasible": False, "objective_value": 101})
    with pytest.raises(ValueError, match="Result differs"):
        summarize(tmp_path)
