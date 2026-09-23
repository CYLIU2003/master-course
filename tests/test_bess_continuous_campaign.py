"""Consecutive-week storage inventory must come from accepted execution."""

from datetime import date, timedelta
import json

import pytest

from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import apply_seasonal_bess_policy
from scripts.benchmarks.run_exact_seasonal_campaign import (
    validate_carryover_weeks,
    verified_bess_carryover,
)


def _accepted_result():
    return {
        "status": "DIAGNOSTIC_EXECUTION_PASSED",
        "physical_accepted": True,
        "accounting_eligible": True,
        "hourly_steps_accepted": 168,
    }


def _write_execution(root, *, final=1325.0, accepted=True):
    chain = root / "rolling_hourly_chain"
    chain.mkdir(parents=True)
    trace = {str(slot): final for slot in range(672)}
    (chain / "executed_plan.json").write_text(
        json.dumps({"bess_soc_kwh_by_depot_slot": {"tsurumaki": trace}}), encoding="utf-8"
    )
    (chain / "physical_validation.json").write_text(
        json.dumps({"accepted": accepted}), encoding="utf-8"
    )
    (chain / "executed_day_accounting.json").write_text(
        json.dumps({"eligible": True, "executed_slot_count": 672, "missing_slots": [],
                    "duplicate_slots": [], "bess_terminal_soc_by_depot": {
                        "tsurumaki": {"terminal_soc_kwh": final}}}), encoding="utf-8"
    )
    return chain


def test_week_selection_rejects_monthly_gaps_and_unverified_initial():
    validate_carryover_weeks(("2025-01-20", "2025-01-27"), {})
    with pytest.raises(ValueError, match="consecutive"):
        validate_carryover_weeks(("2025-01-06", "2025-02-03"), {})
    with pytest.raises(ValueError, match="previous executed plan"):
        validate_carryover_weeks(
            ("2025-01-20", "2025-01-27"), {"bess_initial_soc_override_kwh": 3000}
        )
    with pytest.raises(ValueError, match="Monday"):
        validate_carryover_weeks(("2025-01-21", "2025-01-28"), {})
    assert date.fromisoformat("2025-01-20") + timedelta(days=7) == date.fromisoformat("2025-01-27")


def test_only_accepted_executed_inventory_can_seed_next_week(tmp_path):
    _write_execution(tmp_path)
    transfer = verified_bess_carryover(tmp_path, _accepted_result())
    assert transfer["terminal_soc_kwh"] == 1325
    assert len(transfer["executed_plan_sha256"]) == 64
    parent = {"bess_energy_kwh": 6000, "bess_initial_soc_kwh": 3000}
    next_week = apply_seasonal_bess_policy(parent, design={"bess_initial_soc_override_kwh": transfer["terminal_soc_kwh"]})
    assert parent["bess_initial_soc_kwh"] == 3000
    assert next_week["bess_initial_soc_kwh"] == 1325
    assert next_week["bess_terminal_soc_min_kwh"] == 1200


def test_missing_or_rejected_execution_fails_closed(tmp_path):
    chain = _write_execution(tmp_path, accepted=False)
    with pytest.raises(ValueError, match="physical or accounting"):
        verified_bess_carryover(tmp_path, _accepted_result())
    (chain / "physical_validation.json").write_text('{"accepted": true}', encoding="utf-8")
    plan = chain / "executed_plan.json"
    document = json.loads(plan.read_text(encoding="utf-8"))
    del document["bess_soc_kwh_by_depot_slot"]["tsurumaki"]["671"]
    plan.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="complete 672-slot"):
        verified_bess_carryover(tmp_path, _accepted_result())
    with pytest.raises(ValueError, match="accepted 168-hour"):
        verified_bess_carryover(tmp_path, {**_accepted_result(), "hourly_steps_accepted": 167})


@pytest.mark.parametrize("inventory", [1199.9, 4800.1, float("nan")])
def test_transferred_inventory_must_fit_declared_operating_range(inventory):
    with pytest.raises(ValueError):
        apply_seasonal_bess_policy(
            {"bess_energy_kwh": 6000, "bess_initial_soc_kwh": 3000},
            design={"bess_initial_soc_override_kwh": inventory},
        )


def test_campaign_passes_verified_terminal_only_to_next_prepare(tmp_path, monkeypatch):
    from scripts.benchmarks import prepare_shibu21_24_seasonal_inputs as preparation
    from scripts.benchmarks import run_exact_seasonal_campaign as campaign
    from scripts.benchmarks import run_shibu21_24_seasonal_diagnostic as diagnostic

    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    monkeypatch.setattr(preparation, "build_source_candidate", lambda **_: {"route_codes": ["渋21"]})
    monkeypatch.setattr(diagnostic, "git_state", lambda: {"sha": "frozen", "status_porcelain": ""})
    prepared_designs = []

    def prepare(week, output, source, *, existing, validation_mode, design):
        assert existing is None and validation_mode is True
        prepared_designs.append((week, design))
        return {"formal_prepared": True, "input_preparation_valid": True}

    def solve(design, output):
        _write_execution(output, final=1200.0)
        return [_accepted_result()]

    monkeypatch.setattr(preparation, "prepare_week", prepare)
    monkeypatch.setattr(diagnostic, "run_diagnostic", solve)
    design = {"evaluation_weeks": ["2025-01-20", "2025-01-27"], "route_codes": ["渋21"]}
    summary = campaign.run_campaign(design, tmp_path / "campaign", carry_bess=True)
    assert summary["status"] == "COMPLETED"
    assert len(prepared_designs) == 2
    assert "bess_initial_soc_override_kwh" not in prepared_designs[0][1]
    assert prepared_designs[1][1]["bess_initial_soc_override_kwh"] == 1200.0
    assert prepared_designs[1][1]["bess_initial_soc_override_source"]["week"] == "2025-01-20"
    assert len(summary["summaries"][0]["bess_carryover_boundary"]["executed_plan_sha256"]) == 64


def test_two_week_design_is_separate_from_monthly_selection():
    from tools.research.run_bess_continuous_diagnostic import diagnostic_design

    source = {
        "evaluation_weeks": ["2025-01-06", "2025-02-03"],
        "require_balanced_monthly_weeks": True,
        "bess_terminal_soc_policy": "minimum_only",
    }
    design = diagnostic_design(source)
    assert source["evaluation_weeks"] == ["2025-01-06", "2025-02-03"]
    assert design["evaluation_weeks"] == ["2025-01-20", "2025-01-27"]
    assert design["require_balanced_monthly_weeks"] is False
    assert "UNVERIFIED" in design["physical_import_limit_status"]


def test_continuous_diagnostic_reserves_shared_solver_capacity(tmp_path, monkeypatch):
    from tools.research import run_bess_continuous_diagnostic as entry
    from bff.services.cluster.contracts import ClusterConfig, Worker

    monkeypatch.delenv("MC_CLUSTER_DIR", raising=False)
    monkeypatch.setattr(entry.output_paths, "outputs_root", lambda: tmp_path)
    monkeypatch.setattr(entry, "read_config", lambda: ClusterConfig(
        global_gurobi_slots=2, external_gurobi_slots=1,
        workers=[Worker(id="local", name="local", slots=1)],
    ))
    with entry.shared_solver_capacity(threads=1):
        with pytest.raises(RuntimeError, match="Local solver capacity"):
            with entry.shared_solver_capacity(threads=1):
                pytest.fail("The second local solver must not start")
    with pytest.raises(RuntimeError, match="Shared Gurobi capacity"):
        with entry.shared_solver_capacity(threads=1):
            pytest.fail("The token tail must prevent immediate reuse")
