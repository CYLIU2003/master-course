from __future__ import annotations

import json

from bff.routers.optimization import _rolling_execution_evidence
from src.optimization.rolling.acceptance import (
    ROLLING_CHAIN_REQUIRED_ACCEPTANCE_CHECKS,
)
from scripts.run_research_phase3_frontend_weather import (
    _finalize_day_ahead_rolling_artifacts,
)


def test_rolling_metadata_without_chain_is_not_execution(tmp_path) -> None:
    result = _rolling_execution_evidence(
        run_dir=tmp_path,
        solver_metadata={
            "rolling_horizon_policy": "remaining_day_charging_only_fixed_assignment",
            "rolling_execution_minutes": 60,
        },
    )

    assert result["status"] == "not_executed"


def test_rolling_chain_requires_all_acceptance_checks(tmp_path) -> None:
    rolling_dir = tmp_path / "rolling_hourly_chain"
    rolling_dir.mkdir()
    (rolling_dir / "rolling_chain_summary.json").write_text(
        json.dumps(
            {
                "chain_accepted": True,
                "acceptance_checks": {
                    "all_steps_feasible": True,
                    "executed_day_accounting_eligible": False,
                },
            }
        ),
        encoding="utf-8",
    )

    result = _rolling_execution_evidence(run_dir=tmp_path, solver_metadata={})

    assert result["status"] == "executed_not_accepted"


def test_rolling_chain_with_all_checks_is_accepted(tmp_path) -> None:
    rolling_dir = tmp_path / "rolling_hourly_chain"
    rolling_dir.mkdir()
    (rolling_dir / "rolling_chain_summary.json").write_text(
        json.dumps(
            {
                "chain_accepted": True,
                "execution_minutes": 60,
                "remaining_day_charging_only_fixed_assignment": True,
                "acceptance_checks": {
                    name: True
                    for name in ROLLING_CHAIN_REQUIRED_ACCEPTANCE_CHECKS
                },
            }
        ),
        encoding="utf-8",
    )

    result = _rolling_execution_evidence(run_dir=tmp_path, solver_metadata={})

    assert result["status"] == "executed_and_accepted"
    assert result["rolling_execution_minutes"] == 60


def test_day_ahead_finalizer_rejects_chain_without_passing_checks(tmp_path) -> None:
    (tmp_path / "summary.json").write_text(
        json.dumps({"research_run_accepted": True}), encoding="utf-8"
    )
    (tmp_path / "input_audit.json").write_text("{}", encoding="utf-8")
    rolling_dir = tmp_path / "rolling_hourly_chain"
    rolling_dir.mkdir()
    (rolling_dir / "rolling_chain_summary.json").write_text(
        json.dumps({"chain_accepted": True, "acceptance_checks": {}}),
        encoding="utf-8",
    )

    _finalize_day_ahead_rolling_artifacts(
        day_ahead_output_dir=tmp_path,
        rolling_exit_code=0,
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["rolling_execution"]["status"] == "executed_not_accepted"
    assert "RESEARCH SUBMISSION BLOCKED" in (
        tmp_path / "experiment_report.md"
    ).read_text(encoding="utf-8")


def test_day_ahead_finalizer_does_not_upgrade_blocked_summary(tmp_path) -> None:
    """A rolling chain cannot promote a run blocked by another research gate."""

    (tmp_path / "summary.json").write_text(
        json.dumps(
            {
                "research_run_accepted": True,
                "research_submission_ready": False,
                "teacher_release_status": "BLOCKED",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "input_audit.json").write_text("{}", encoding="utf-8")
    rolling_dir = tmp_path / "rolling_hourly_chain"
    rolling_dir.mkdir()
    (rolling_dir / "rolling_chain_summary.json").write_text(
        json.dumps(
            {
                "chain_accepted": True,
                "acceptance_checks": {
                    name: True for name in ROLLING_CHAIN_REQUIRED_ACCEPTANCE_CHECKS
                },
            }
        ),
        encoding="utf-8",
    )

    _finalize_day_ahead_rolling_artifacts(
        day_ahead_output_dir=tmp_path,
        rolling_exit_code=0,
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    report = (tmp_path / "experiment_report.md").read_text(encoding="utf-8")
    assert summary["research_submission_ready"] is False
    assert summary["teacher_release_status"] == "BLOCKED"
    assert "research_submission_ready: False" in report
    assert "RESEARCH SUBMISSION BLOCKED" in report
