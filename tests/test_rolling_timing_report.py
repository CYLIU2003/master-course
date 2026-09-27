import json
from pathlib import Path

import pytest

from tools.research.rolling_timing_report import inspect_run, main, native_timings, number


def evidence(tmp_path: Path, index=0, native=True) -> Path:
    root = tmp_path / "run"
    step = root / "rolling_hourly_chain" / f"step_{index:02}_0000"
    step.mkdir(parents=True)
    (step / "hourly_summary.json").write_text(json.dumps({"step_index": index,
        "elapsed_seconds": 50, "stage2_runtime_seconds": 45, "time_limit_sec": 600,
        "stage2_solver_status": "optimal", "feasible": True}), encoding="utf-8")
    (step / "hourly_solver_result.json").write_text(json.dumps({"metadata": {
        "stage2_native_log_path": f"C:\\other-machine\\run\\diagnostics\\stage2_native_{index}.log"}}), encoding="utf-8")
    if native:
        (root / "diagnostics").mkdir(exist_ok=True)
        (root / "diagnostics" / f"stage2_native_{index}.log").write_text(
            "Root relaxation: objective 1, 5 iterations, 8.00 seconds\n"
            "Explored 123 nodes (42 simplex iterations) in 30.00 seconds (4 work units)\n", encoding="utf-8")
    return root


def test_native_runtime_excludes_root_and_barrier_substeps():
    assert native_timings(b"Barrier solved model in 9 iterations and 4.00 seconds\n"
                          b"Solved in 9 iterations and 5.00 seconds\n"
                          b"Explored 2 nodes (33 simplex iterations) in 7.50 seconds\n") == [5, 7.5]


def test_measures_logs_not_helper_runtime_and_binds_sources(tmp_path):
    report = inspect_run(evidence(tmp_path))
    assert report["paired_native_seconds"] == 30
    assert report["paired_outside_native_seconds"] == 20
    assert report["steps"][0]["stage2_helper_elapsed_seconds"] == 45
    assert len(report["evidence_sha256"]) == 3
    assert all(len(v) == 64 for v in report["evidence_sha256"].values())


def test_missing_log_is_not_zero(tmp_path):
    report = inspect_run(evidence(tmp_path, native=False))
    assert report["paired_steps"] == 0
    assert report["missing_native_steps"] == [0]
    assert report["steps"][0]["native_optimize_seconds"] is None


def test_unfinished_log_is_unknown(tmp_path):
    root = evidence(tmp_path)
    (root / "diagnostics/stage2_native_0.log").write_text("Optimize a model\n")
    assert inspect_run(root)["steps"][0]["native_evidence"] == "NO_TERMINATION_LINE"


def test_orders_indices_numerically(tmp_path):
    root = evidence(tmp_path, 100)
    evidence(tmp_path, 99)
    assert [r["step_index"] for r in inspect_run(root)["steps"]] == [99, 100]


def test_rejects_wrong_log_binding_by_elapsed_time(tmp_path):
    root = evidence(tmp_path)
    (root / "diagnostics/stage2_native_0.log").write_text(
        "Explored 1 nodes (2 simplex iterations) in 60.00 seconds\n")
    with pytest.raises(ValueError, match="exceeds"):
        inspect_run(root)


def test_rejects_duplicate_steps(tmp_path):
    root = evidence(tmp_path)
    evidence(tmp_path, 1)
    p = root / "rolling_hourly_chain/step_01_0000/hourly_summary.json"
    p.write_text(json.dumps({"step_index": 0}))
    with pytest.raises(ValueError, match="duplicate"):
        inspect_run(root)


def test_reports_sequential_native_calls_as_cumulative_time(tmp_path):
    root = evidence(tmp_path)
    with (root / "diagnostics/stage2_native_0.log").open("a") as stream:
        stream.write("Explored 2 nodes (4 simplex iterations) in 5.00 seconds\n")
    report = inspect_run(root)
    assert report["paired_native_seconds"] == 35
    assert report["paired_outside_native_seconds"] == 15
    assert report["multiple_native_solve_steps"] == [0]


def test_rejects_misnamed_step_directory(tmp_path):
    root = evidence(tmp_path)
    p = root / "rolling_hourly_chain/step_00_0000"
    p.rename(p.with_name("step_05_0000"))
    with pytest.raises(ValueError, match="disagrees"):
        inspect_run(root)


def test_cli_never_writes_inside_evidence(tmp_path, monkeypatch):
    root = evidence(tmp_path)
    target = root / "timing.json"
    monkeypatch.setattr("sys.argv", ["timings", "--run", str(root), "--output", str(target)])
    with pytest.raises(SystemExit):
        main()
    assert not target.exists()


def test_cli_never_overwrites_a_previous_report(tmp_path, monkeypatch):
    root = evidence(tmp_path)
    target = tmp_path / "timing.json"
    target.write_bytes(b"original")
    monkeypatch.setattr("sys.argv", ["timings", "--run", str(root), "--output", str(target)])
    with pytest.raises(FileExistsError):
        main()
    assert target.read_bytes() == b"original"


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), "5"])
def test_invalid_values_remain_unknown(value):
    assert number(value) is None
