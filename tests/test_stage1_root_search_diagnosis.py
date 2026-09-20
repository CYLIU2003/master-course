import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import scripts.benchmarks.run_stage1_root_search_diagnosis as runner


def setup(monkeypatch, tmp_path, *, fail=False):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "git_state", lambda: {"sha": "frozen", "status_porcelain": ""})
    design = tmp_path / "design.json"
    design.write_text(json.dumps({"diagnostic_profiles": list(runner.PROFILES)}))
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        folder = Path(command[-1])
        folder.mkdir()
        if fail:
            return SimpleNamespace(returncode=1)
        (folder / "summary.json").write_text(json.dumps({
            "physical_accepted": True, "quality": {"subproblem_gap_targets_met": False},
            "daily_path_cover_bounds": {"0": 2}, "stage1_native_log_path": "native.log"}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", execute)
    return design, calls


def test_root_profiles_run_once_sequentially_in_separate_outputs(monkeypatch, tmp_path):
    design, calls = setup(monkeypatch, tmp_path)
    result = runner.run(design, tmp_path / "output")
    assert len(calls) == 2
    assert calls[0][-1] != calls[1][-1]
    assert [r["profile"] for r in result["results"]] == list(runner.PROFILES)
    assert result["status"] == "ROOT_SEARCH_DIAGNOSIS_COMPLETE"
    assert not result["monthly_complete"] and not result["email_sent"]


def test_root_diagnosis_stops_after_failure_without_retry(monkeypatch, tmp_path):
    design, calls = setup(monkeypatch, tmp_path, fail=True)
    with pytest.raises(RuntimeError, match="no automatic retry"):
        runner.run(design, tmp_path / "output")
    assert len(calls) == 1
    failure = json.loads((tmp_path / "output/failure.json").read_text())
    assert failure["status"] == "ROOT_SEARCH_DIAGNOSIS_FAILED"
    assert not failure["email_sent"]
