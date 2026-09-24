import pytest

from tools.research.shibu24_staged_campaign import require_gate


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
