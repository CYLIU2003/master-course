"""Fail closed before submitting a monthly overnight campaign."""

import json

import pytest

from src.optimization.common.date_series import content_hash
from tools.research import shibu24_monthly as monthly


def _frozen_campaign(tmp_path, monkeypatch):
    sha = "a" * 40
    weeks = [f"2025-{month:02d}-06" for month in range(1, 13)]
    monkeypatch.setattr(monthly, "git_state", lambda path: {"sha": sha, "dirty": False})
    monkeypatch.setattr(monthly, "check", lambda: {"status": "checked"})
    monkeypatch.setattr(monthly, "_source_and_design", lambda: ({}, {}, weeks))
    settings = {"git_sha": sha, "release": str(tmp_path / "release"),
                "outputs": str(tmp_path / "controller"), "port": 8868}
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    output = tmp_path / "campaign"
    output.mkdir()
    binding = {"git_sha": sha, "preflight_hash": content_hash(monthly.check()), "weeks": weeks}
    monthly._write(output / "binding.json", binding)
    monthly._write(output / "summary.json", {"all_prepared": True, "binding": binding,
                                              "cases": [{} for _ in weeks]})
    for week in weeks:
        scenario_id = f"scenario-{week[:7]}"
        prepared_id = f"prepared-{week[:7]}"
        prepared = tmp_path / "controller" / "prepared_inputs" / scenario_id / f"{prepared_id}.json"
        prepared.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_text(f'{{"week":"{week}"}}', encoding="utf-8")
        monthly._write(output / week / "state.json", {
            "week": week, "status": "PREPARED", "strict_scope_audit_passed": True,
            "scenario_id": scenario_id, "prepared_input_id": prepared_id,
            "prepared_input_sha256": monthly._sha(prepared),
        })
    return settings_path, output, weeks


def test_monthly_batch_requires_twelve_hashed_prepared_inputs(tmp_path, monkeypatch):
    settings, output, weeks = _frozen_campaign(tmp_path, monkeypatch)
    result = monthly.create_batch(output, settings, "monthly-diag", minimum_ram_gb=18)
    spec = monthly._read(output / "batch.json")
    assert result["tasks"] == 12
    assert [task["task_id"] for task in spec["tasks"]] == [
        f"month-{week[:7]}" for week in weeks
    ]
    assert all(task["submission"]["request"]["run_profile"] ==
               "day_ahead_and_hourly_rolling" for task in spec["tasks"])
    assert all(task["submission"]["request"]["research_run"] is False
               for task in spec["tasks"])


def test_monthly_batch_rejects_prepared_file_changed_after_audit(tmp_path, monkeypatch):
    settings, output, _ = _frozen_campaign(tmp_path, monkeypatch)
    path = next((tmp_path / "controller" / "prepared_inputs").rglob("*.json"))
    path.write_text('{"tampered":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="Prepared input changed"):
        monthly.create_batch(output, settings, "monthly-diag", minimum_ram_gb=18)
    assert not (output / "batch.json").exists()
