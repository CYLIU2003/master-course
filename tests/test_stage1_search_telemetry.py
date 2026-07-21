from src.optimization.milp.solver_adapter import _Stage1SearchTelemetry


def test_stage1_search_telemetry_samples_progress_and_gap_time() -> None:
    telemetry = _Stage1SearchTelemetry(
        requested_gap_ratio=0.025,
        sample_interval_sec=5.0,
    )

    telemetry.record_progress(
        runtime_sec=0.5,
        incumbent_objective=1.0e100,
        best_bound=1.0e100,
        explored_node_count=0,
        solution_count=0,
    )
    telemetry.record_progress(
        runtime_sec=2.0,
        incumbent_objective=110.0,
        best_bound=90.0,
        explored_node_count=3,
        solution_count=1,
    )
    telemetry.record_progress(
        runtime_sec=5.5,
        incumbent_objective=102.0,
        best_bound=100.0,
        explored_node_count=12,
        solution_count=2,
    )

    assert len(telemetry.progress_samples) == 2
    assert telemetry.progress_samples[0]["incumbent_objective"] is None
    assert telemetry.requested_gap_reached_runtime_sec == 5.5


def test_stage1_search_telemetry_records_first_incumbent_and_final_counts() -> None:
    telemetry = _Stage1SearchTelemetry(
        requested_gap_ratio=0.01,
        max_incumbent_events=1,
    )

    telemetry.record_incumbent(
        runtime_sec=7.0,
        incumbent_objective=105.0,
        best_bound=90.0,
        explored_node_count=4,
        solution_count=1,
    )
    telemetry.record_incumbent(
        runtime_sec=9.0,
        incumbent_objective=101.0,
        best_bound=99.0,
        explored_node_count=8,
        solution_count=2,
    )
    result = telemetry.to_dict(
        final_runtime_sec=12.0,
        final_incumbent_objective=100.0,
        final_best_bound=99.5,
        final_node_count=20,
        final_solution_count=3,
        final_simplex_iteration_count=123,
        final_barrier_iteration_count=4,
    )

    assert result["first_incumbent_runtime_sec"] == 7.0
    assert result["requested_gap_reached_runtime_sec"] == 12.0
    assert result["incumbent_notification_count"] == 2
    assert result["retained_incumbent_event_count"] == 1
    assert result["dropped_incumbent_event_count"] == 1
    assert result["final"]["explored_node_count"] == 20
    assert result["final"]["solution_count"] == 3
    assert result["final_simplex_iteration_count"] == 123.0
    assert result["final_barrier_iteration_count"] == 4.0
