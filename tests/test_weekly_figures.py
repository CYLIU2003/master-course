import json

import pytest

from tools.research import weekly_figures as figures
from tools.research.weekly_results import write_csv, write_json


def saved_numbers(path):
    path.mkdir()
    row = {"evaluation_status": "VERIFIED_CONDITIONAL_WEEKLY_EVALUATION", "total_cost": 123,
           "original_research_verdict": {"teacher_release_status": "BLOCKED"}}
    write_json(path / "weekly_summary.json", row)
    for name in figures.NUMERICAL_FILES[1:]:
        write_csv(path / name, [{"slot": 1, "vehicle_id": "bus", "soc_percent": 80}])
    return row


def test_plot_failure_preserves_verified_numbers_and_original_verdict(tmp_path, monkeypatch):
    source = tmp_path / "results"
    row = saved_numbers(source)
    before = figures.hashes(source)
    def fail(*args):
        raise RuntimeError("font rendering failed")
    monkeypatch.setattr(figures, "render_week", fail)
    result = figures.render_verified_week(source, row, [], [], before)
    assert result["figure_status"] == "FAILED" and result["numerical_status"] == "VERIFIED"
    assert result["error"] == "font rendering failed"
    assert figures.hashes(source) == before
    assert json.loads((source / "weekly_summary.json").read_text())["original_research_verdict"]["teacher_release_status"] == "BLOCKED"

    def render(output, saved, times, soc):
        assert saved["total_cost"] == 123
        assert times[0]["slot"] == 1.0 and soc[0]["vehicle_id"] == "bus"
        (output / "weekly_energy_soc.png").write_bytes(b"test figure")
    monkeypatch.setattr(figures, "render_week", render)
    output = tmp_path / "retry"
    retry = figures.retry_figures(source, output)
    assert retry["figure_status"] == "COMPLETED" and not retry["solver_restarted"]
    assert figures.hashes(source) == before
    with pytest.raises(FileExistsError):
        figures.retry_figures(source, output)
    (source / "daily_summary.csv").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        figures.retry_figures(source, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
