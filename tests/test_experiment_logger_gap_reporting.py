from __future__ import annotations

import json

from bff.services import experiment_reports
from experiment_logger import ExperimentLogger


def test_two_stage_report_separates_requested_raw_and_certified_gaps(tmp_path) -> None:
    logger = ExperimentLogger(results_dir=tmp_path)
    report = logger.log(
        scenario={
            "depot": "tsurumaki",
            "routes": ["R1"],
            "fleet": [
                {"vehicle_type": "BEV", "model": "BEV", "count": 35},
                {"vehicle_type": "ICE", "model": "ICE", "count": 26},
            ],
            "objective": "total_cost",
            "solver": {"name": "gurobi", "time_limit_sec": 1500},
            "costs": {"tou_rates": {}},
            "grid": {"max_kw": 1000.0},
        },
        result={
            "status": "FEASIBLE",
            "mip_gap_pct": 100.0,
            "bev_terminal_soc_policy": "return_to_initial",
            "bev_terminal_soc_balance_satisfied": True,
            "bev_terminal_soc_total_drawdown_kwh": 0.0,
        },
        extra_solver={
            "mip_gap_requested_pct": 10.0,
            "stage1_gurobi_raw_mip_gap_pct": 100.0,
            "stage1_certified_mip_gap_pct": 9.204876,
            "stage1_certified_mip_gap_semantics": "analytical_lower_bound",
            "stage1_termination_reason": "time_limit",
            "threads": 1,
        },
        git_commit="abc123",
    )

    markdown = report.md_path.read_text(encoding="utf-8")
    report_json = json.loads(report.json_path.read_text(encoding="utf-8"))

    assert "| MIP Gap 要求 (Gurobi) | 10.000 % |" in markdown
    assert "| Stage 1 Gurobi native gap | 100.0000 % |" in markdown
    assert "| Stage 1 certified gap | 9.2049 % |" in markdown
    assert "| Stage 1 termination | `time_limit` |" in markdown
    assert "| MIP Gap 目標 |" not in markdown
    assert "| MIP Gap 実績 |" not in markdown
    assert "| BEV終端SOC方針 | `return_to_initial` |" in markdown
    assert "| BEV終端SOC収支 | OK |" in markdown
    assert report_json["solver_settings"]["mip_gap_requested_pct"] == 10.0
    assert report_json["solver_settings"]["stage1_gurobi_raw_mip_gap_pct"] == 100.0


def test_bff_report_service_passes_two_stage_gap_semantics_to_logger(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        experiment_reports,
        "_results_dir",
        lambda _scenario_id, _report_type: tmp_path,
    )
    payload = experiment_reports.log_optimization_experiment(
        scenario_id="scenario-1",
        scenario_doc={
            "dispatch_scope": {"depotId": "tsurumaki"},
            "vehicles": [
                {"id": "bev-1", "type": "BEV"},
                {"id": "ice-1", "type": "ICE"},
            ],
            "simulation_config": {},
            "scenario_overlay": {"solver_config": {"mip_gap": 0.1}},
        },
        optimization_result={
            "mode": "mode_milp_only",
            "objective_mode": "total_cost",
            "solver_status": "FEASIBLE",
            "summary": {},
            "solver_metadata": {
                "executed_phase": "phase3_two_stage",
                "bev_terminal_soc_policy": "return_to_initial",
                "bev_terminal_soc_balance_satisfied": True,
                "bev_terminal_soc_total_drawdown_kwh": 0.0,
            },
            "solver_settings": {
                "mip_gap_requested_percent": 10.0,
                "mip_gap_achieved_percent": 9.204876,
                "stage1_gurobi_raw_mip_gap_percent": 100.0,
                "stage1_certified_mip_gap_percent": 9.204876,
                "stage1_certified_mip_gap_semantics": "analytical_lower_bound",
                "stage1_termination_reason": "time_limit",
                "gurobi_threads": 1,
            },
            "cost_breakdown": {"total_cost": 1.0},
        },
        git_commit_override="abc123",
    )

    markdown = (tmp_path / next(path.name for path in tmp_path.glob("*.md"))).read_text(
        encoding="utf-8"
    )

    assert payload["method"] == "二段階MILP"
    assert "| MIP Gap 要求 (Gurobi) | 10.000 % |" in markdown
    assert "| Stage 1 Gurobi native gap | 100.0000 % |" in markdown
    assert "| Stage 1 certified gap | 9.2049 % |" in markdown
