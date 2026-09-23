"""Prepared and actual-PV inputs remain immutable across controller staging."""

import hashlib
import json

import pytest

from tools.research import stage_shibu24_monthly_inputs as staging


def test_stage_twelve_exact_inputs_and_reject_changed_controller_copy(tmp_path, monkeypatch):
    sha = "a" * 40
    source = tmp_path / "source"
    release = tmp_path / "release"
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    monkeypatch.setattr(staging, "git_state", lambda path: {"sha": sha, "dirty": False})
    weeks = [f"2025-{month:02d}-06" for month in range(1, 13)]
    binding = {"git_sha": sha, "weeks": weeks}
    (campaign / "binding.json").write_text(json.dumps(binding), encoding="utf-8")
    (campaign / "summary.json").write_text(
        json.dumps({"all_prepared": True, "binding": binding}), encoding="utf-8")
    (source / "output/scenarios").mkdir(parents=True)
    actual_name = "data/derived/pv_execution_inputs/tsurumaki/actual.json"
    actual = source / actual_name
    actual.parent.mkdir(parents=True)
    actual.write_text('{"verified":true}', encoding="utf-8")
    actual_sha = hashlib.sha256(actual.read_bytes()).hexdigest()
    for week in weeks:
        scenario_id, prepared_id = f"scenario-{week[:7]}", f"prepared-{week[:7]}"
        prepared = source / "output/prepared_inputs" / scenario_id / f"{prepared_id}.json"
        prepared.parent.mkdir(parents=True)
        prepared.write_text(json.dumps({"scenario_id": scenario_id,
            "prepared_input_id": prepared_id,
            "simulation_config": {"date_series_contract": {"pv_execution_input": {
                "path": actual_name, "sha256": actual_sha}}}}), encoding="utf-8")
        state = {"week": week, "status": "PREPARED", "strict_scope_audit_passed": True,
                 "scenario_id": scenario_id, "prepared_input_id": prepared_id,
                 "prepared_input_sha256": hashlib.sha256(prepared.read_bytes()).hexdigest()}
        folder = campaign / week
        folder.mkdir()
        (folder / "state.json").write_text(json.dumps(state), encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"git_sha": sha, "release": str(release),
        "outputs": str(tmp_path / "controller"),
        "scenarios": str(source / "output/scenarios")}), encoding="utf-8")

    result = staging.stage(campaign, source, settings)
    assert len(result["cases"]) == 12
    assert (release / actual_name).read_bytes() == actual.read_bytes()
    assert staging.stage(campaign, source, settings) == result
    target = tmp_path / "controller/prepared_inputs/scenario-2025-01/prepared-2025-01.json"
    target.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Refusing to replace different"):
        staging.stage(campaign, source, settings)
