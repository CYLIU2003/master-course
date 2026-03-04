"""
tests/test_pipeline_solve_dispatch_report.py

Checks dispatch preprocess logging in solve() when report is dict-shaped
(build_inputs path).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.data_schema import ProblemData, Task, Vehicle
from src.pipeline import solve as solve_module


class _DummyResult:
    status = "OPTIMAL"
    objective_value = 123.0
    solve_time_sec = 0.01
    mip_gap = 0.0
    unserved_tasks: tuple[str, ...] = tuple()


def _make_data_with_build_inputs_report() -> ProblemData:
    data = ProblemData(
        vehicles=[Vehicle(vehicle_id="B1", vehicle_type="BEV", home_depot="D1")],
        tasks=[
            Task(
                task_id="T1",
                start_time_idx=0,
                end_time_idx=1,
                origin="A",
                destination="B",
            )
        ],
        chargers=[],
        sites=[],
        num_periods=4,
        delta_t_hour=0.25,
    )
    setattr(
        data,
        "_dispatch_preprocess_report",
        {
            "source": "build_inputs",
            "trip_count": 2,
            "edge_count": 1,
            "generated_connections": 2,
            "vehicle_types": tuple(),
            "warnings": tuple(),
        },
    )
    return data


def test_solve_logs_build_inputs_dispatch_report(tmp_path: Path, monkeypatch, capsys):
    cfg = {
        "mode": "mode_milp_only",
        "solver": {"time_limit_sec": 1, "mip_gap": 0.5},
        "paths": {"output_dir": str(tmp_path / "outputs")},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    data = _make_data_with_build_inputs_report()

    monkeypatch.setattr("src.data_loader.load_problem_data", lambda _p: data)
    monkeypatch.setattr("src.model_sets.build_model_sets", lambda _d: object())
    monkeypatch.setattr(
        "src.parameter_builder.build_derived_params", lambda _d, _ms: object()
    )
    monkeypatch.setattr(
        solve_module,
        "_solve_milp_core",
        lambda *_args, **_kwargs: (_DummyResult(), 0.01),
    )

    out = solve_module.solve(str(cfg_path), mode="mode_milp_only")
    printed = capsys.readouterr().out

    assert "[dispatch] source=build_inputs" in printed
    assert "trips=2" in printed
    assert "edges=1" in printed
    assert "connections=2" in printed
    assert out["dispatch_preprocess"]["source"] == "build_inputs"
