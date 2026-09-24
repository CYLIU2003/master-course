import pytest
import json
import zipfile

from tools.research.shibu24_staged_campaign import (
    WEEK_MINIMUM_FREE_RAM_GB, batch_failure_detail, require_gate, require_week_capacity,
)


def test_stage_gate_requires_collected_physical_evidence():
    report = {"total": 1, "unverified": 0,
              "tasks": [{"task_id": "day", "collection_verified": True,
                         "physical_feasibility_claim_eligible": True}]}
    require_gate(report, 1)
    report["tasks"][0]["physical_feasibility_claim_eligible"] = False
    with pytest.raises(ValueError, match="physical-feasibility"):
        require_gate(report, 1)


def test_stage_gate_rejects_incomplete_batch_even_if_task_has_physical_flag():
    report = {"total": 12, "unverified": 1,
              "tasks": [{"task_id": "may", "physical_feasibility_claim_eligible": True}]}
    with pytest.raises(ValueError, match="hash/contract"):
        require_gate(report, 12)


def test_failed_batch_surfaces_memory_failure_without_full_traceback(tmp_path):
    assert WEEK_MINIMUM_FREE_RAM_GB > 12
    archive = tmp_path / "job.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("state.json", json.dumps({"result": {
            "error": "Traceback\nsecret or unrelated details\ngurobipy.GurobiError: Out of memory"
        }}))
    (tmp_path / "batch-state.json").write_text(json.dumps({"tasks": {
        "may": {"state": "FAILED", "artifacts": archive.name},
    }}), encoding="utf-8")

    assert batch_failure_detail(tmp_path) == "may: GurobiError: Out of memory"


def test_unresolved_batch_never_claims_failure_or_success(tmp_path):
    (tmp_path / "batch-state.json").write_text(json.dumps({"tasks": {
        "may": {"state": "UNKNOWN", "job_id": "attempt-1"},
    }}), encoding="utf-8")
    assert "same attempt requires reconciliation" in batch_failure_detail(tmp_path)


def test_local_only_week_rejects_insufficient_free_ram_before_submission(tmp_path, monkeypatch):
    config = tmp_path / "workers.json"
    config.write_text(json.dumps({"workers": [
        {"id": "local", "enabled": True, "transport": "local", "reserved_system_ram_gb": 2}
    ]}), encoding="utf-8")
    monkeypatch.setattr("tools.research.shibu24_staged_campaign.memory_metrics",
                        lambda: {"ram_free_gb": 21})
    with pytest.raises(ValueError, match="No job was submitted"):
        require_week_capacity({"config": str(config)}, 20)
    monkeypatch.setattr("tools.research.shibu24_staged_campaign.memory_metrics",
                        lambda: {"ram_free_gb": 23})
    require_week_capacity({"config": str(config)}, 20)
