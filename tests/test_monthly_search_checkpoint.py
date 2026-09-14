"""The new release must never publish a failed or foreign weekly audit."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from scripts.watch_monthly_campaign import sha256, write_json


@pytest.mark.parametrize("mutation", [None, "failed", "pending", "source", "campaign", "case"])
def test_checkpoint_requires_accepted_evidence_from_its_campaign(tmp_path, monkeypatch, mutation):
    source = Path(__file__).resolve().parents[1] / "output/monthly_search_20260915/update_monthly_checkpoint.py"
    spec = importlib.util.spec_from_file_location("search_checkpoint_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = tmp_path / "control"
    frozen = tmp_path / "frozen"
    campaign = frozen / "output/campaign"
    week = "2025-01-06"
    launch = {"source_git_sha": "test-sha", "frozen_root": str(frozen), "campaign_relative_path": "output/campaign"}
    row = {"fully_audited": True, "status": "DIAGNOSTIC_EXECUTION_PASSED", "audit_status": "INDEPENDENTLY_AUDITED",
           "case_root": str(campaign / "cases" / week / "diagnostic" / week)}
    audit = {"expected_sha": "test-sha", "frozen_root": str(frozen), "campaign_output": "output/campaign", "weeks": {week: row}}
    if mutation == "failed":
        row["failure"] = True
    elif mutation == "pending":
        row["audit_status"] = "PENDING"
    elif mutation == "source":
        audit["frozen_root"] = str(tmp_path / "old-frozen")
    elif mutation == "campaign":
        audit["campaign_output"] = "output/old"
    elif mutation == "case":
        row["case_root"] = str(campaign / "old-case")
    write_json(base / "budget_rerun_launch.json", launch)
    audit_path = base / "monthly_budget_independent_audit.json"
    write_json(audit_path, audit)
    write_json(campaign / "progress.json", {"base_git_sha": "test-sha", "completed_weeks": [week]})
    write_json(tmp_path / "docs/notes/SHIBU21_23_MONTHLY_SEARCH_RESULTS_20260915.json",
               {"source_git_sha": "test-sha", "independent_audit": {"sha256": sha256(audit_path)},
                "weeks": [{"week": week}], "completed_count": 1, "status": "IN_PROGRESS"})
    for name in ["README.md", "DEVELOPMENT_NOTES.md", "docs/notes/CURRENT_RESEARCH_RELEASE_BLOCKERS.md",
                 "docs/notes/SHIBU21_23_MONTHLY_FAIR_WEEKS_20260914.md"]:
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text("# User document\n\nPreserved text\n", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "BASE", base)
    monkeypatch.setattr(sys, "argv", ["checkpoint", "--dry-run"])
    if mutation:
        with pytest.raises(ValueError):
            module.main()
    else:
        module.main()
    assert "monthly-search-status" not in (tmp_path / "README.md").read_text()
