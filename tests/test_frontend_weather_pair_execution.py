from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_frontend_controlled_pv_pair.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_frontend_controlled_pv_pair",
        RUNNER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_has_no_optimization_domain_imports() -> None:
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    imported_symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                alias.name.split(".", maxsplit=1)[0]
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_roots.add(node.module.split(".", maxsplit=1)[0])
            imported_symbols.update(alias.name for alias in node.names)

    assert imported_roots <= {
        "__future__",
        "argparse",
        "csv",
        "datetime",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "platform",
        "shutil",
        "subprocess",
        "sys",
        "time",
        "typing",
        "urllib",
        "zipfile",
    }
    assert {
        "OptimizationEngine",
        "ProblemBuilder",
        "GurobiMILPAdapter",
        "run_research_phase3_frontend_weather",
    }.isdisjoint(imported_symbols)


def test_prepare_payload_separates_service_date_from_pv_source() -> None:
    runner = _load_runner()
    sunny = runner.build_prepare_payload(
        depot_id="tsurumaki",
        service_id="WEEKDAY",
        service_date="2025-08-05",
        pv_source_date="2025-08-05",
        comparison_role="baseline",
    )
    rain = runner.build_prepare_payload(
        depot_id="tsurumaki",
        service_id="WEEKDAY",
        service_date="2025-08-05",
        pv_source_date="2025-08-10",
        comparison_role="pv_curve_counterfactual",
    )

    assert sunny["service_date"] == rain["service_date"] == "2025-08-05"
    assert sunny["day_type"] == rain["day_type"] == "WEEKDAY"
    assert sunny["selected_depot_ids"] == rain["selected_depot_ids"] == [
        "tsurumaki"
    ]
    assert (
        sunny["selected_route_ids"]
        == rain["selected_route_ids"]
        == list(runner.TARGET_ROUTE_IDS_BY_DEPOT["tsurumaki"])
    )
    assert len(sunny["selected_route_ids"]) == 16
    sunny_settings = sunny["simulation_settings"]
    rain_settings = rain["simulation_settings"]
    assert (
        sunny_settings["comparison_type"]
        == rain_settings["comparison_type"]
        == "same_service_date_pv_counterfactual"
    )
    assert sunny_settings["counterfactual_pv_source_date"] == "2025-08-05"
    assert rain_settings["counterfactual_pv_source_date"] == "2025-08-10"
    assert sunny_settings["pv_profile_id"] == (
        "tsurumaki_2025-08-05_60min"
    )
    assert rain_settings["pv_profile_id"] == (
        "tsurumaki_2025-08-10_60min"
    )
    assert sunny_settings["enable_weather_operation_policy"] is False
    assert rain_settings["enable_weather_operation_policy"] is False
    for field, expected in (
        ("initial_ice_fuel_percent", 100.0),
        ("min_ice_fuel_percent", 10.0),
        ("max_ice_fuel_percent", 90.0),
        ("final_soc_floor_percent", 20.0),
        ("final_soc_target_percent", 80.0),
        ("final_soc_target_tolerance_percent", 20.0),
    ):
        assert sunny_settings[field] == rain_settings[field] == expected
    assert (
        sunny_settings["cost_component_flags"]
        == rain_settings["cost_component_flags"]
        == runner.CONTROLLED_COST_COMPONENT_FLAGS
    )


def test_optimization_payloads_match_except_fresh_prepared_id() -> None:
    runner = _load_runner()
    sunny = runner.build_optimization_payload("prepared-sunny-fresh")
    rain = runner.build_optimization_payload("prepared-rain-fresh")
    sunny_without_id = {
        key: value
        for key, value in sunny.items()
        if key != "prepared_input_id"
    }
    rain_without_id = {
        key: value
        for key, value in rain.items()
        if key != "prepared_input_id"
    }

    assert sunny_without_id == rain_without_id
    assert sunny["stage1_stage2_candidate_limit"] >= 21
    assert sunny["stage1_best_obj_stop_enabled"] is False
    assert sunny["enableWeatherOperationPolicy"] is False
    assert sunny["run_hourly_rolling"] is True
    assert sunny["rolling_execution_minutes"] == 60
    assert sunny["mip_gap"] == 0.1


def test_case_execution_uses_formal_timeout_for_synchronous_prepare(
    tmp_path: Path,
) -> None:
    runner = _load_runner()

    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, float]] = []

        def request_json(
            self,
            method: str,
            path: str,
            payload: dict | None = None,
            *,
            timeout_seconds: float = 120.0,
        ) -> tuple[dict, str]:
            del payload
            self.calls.append((method, path, timeout_seconds))
            if path.endswith("/simulation/prepare"):
                response = {
                    "ready": True,
                    "preparedInputId": "prepared-fresh-timeout-test",
                    "routeCount": 16,
                    "tripCount": 264,
                }
            elif path.endswith("/run-optimization"):
                response = {"job_id": "job-timeout-test"}
            elif path == "/api/jobs/job-timeout-test":
                response = {
                    "status": "failed",
                    "progress": 100,
                    "message": "intentional terminal test state",
                    "metadata": {},
                }
            else:  # pragma: no cover - fail loudly on an unexpected call
                raise AssertionError(path)
            return response, json.dumps(response)

    client = RecordingClient()
    runner._execute_case(
        name="sunny",
        scenario_id="scenario-timeout-test",
        prepare_payload=runner.build_prepare_payload(
            depot_id="tsurumaki",
            service_id="WEEKDAY",
            service_date="2025-08-05",
            pv_source_date="2025-08-05",
            comparison_role="baseline",
        ),
        client=client,
        output_dir=tmp_path,
        timeout_seconds=987.0,
        poll_interval_seconds=0.0,
        frozen_sha="a" * 40,
        log=[],
    )

    assert client.calls[0] == (
        "POST",
        "/api/scenarios/scenario-timeout-test/simulation/prepare",
        987.0,
    )
    assert client.calls[1] == (
        "POST",
        "/api/scenarios/scenario-timeout-test/run-optimization",
        987.0,
    )


def test_case_execution_fails_closed_on_materialized_route_scope_drift(
    tmp_path: Path,
) -> None:
    runner = _load_runner()

    class DriftedPrepareClient:
        def request_json(
            self,
            method: str,
            path: str,
            payload: dict | None = None,
            *,
            timeout_seconds: float = 120.0,
        ) -> tuple[dict, str]:
            del method, payload, timeout_seconds
            assert path.endswith("/simulation/prepare")
            response = {
                "ready": True,
                "preparedInputId": "prepared-drifted-scope",
                "routeCount": 56,
                "tripCount": 974,
            }
            return response, json.dumps(response)

    with pytest.raises(
        RuntimeError,
        match="Prepare route scope mismatch: requested 16, materialized 56",
    ):
        runner._execute_case(
            name="sunny",
            scenario_id="scenario-scope-drift-test",
            prepare_payload=runner.build_prepare_payload(
                depot_id="tsurumaki",
                service_id="WEEKDAY",
                service_date="2025-08-05",
                pv_source_date="2025-08-05",
                comparison_role="baseline",
            ),
            client=DriftedPrepareClient(),
            output_dir=tmp_path,
            timeout_seconds=987.0,
            poll_interval_seconds=0.0,
            frozen_sha="a" * 40,
            log=[],
        )


def test_vehicle_trip_assignments_are_complete_and_chronological() -> None:
    runner = _load_runner()
    assignments = {
        "trip-late": {
            "trip_id": "trip-late",
            "route": "r2",
            "departure_time": "12:00",
            "vehicle_id": "bev-1",
            "powertrain": "BEV",
        },
        "trip-early": {
            "trip_id": "trip-early",
            "route": "r1",
            "departure_time": "08:00",
            "vehicle_id": "bev-1",
            "powertrain": "BEV",
        },
    }

    grouped = runner._vehicle_trip_assignments(assignments)

    assert list(grouped) == ["bev-1"]
    assert [row["trip_id"] for row in grouped["bev-1"]] == [
        "trip-early",
        "trip-late",
    ]


def test_bess_terminal_soc_reads_executed_day_terminal_record(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    rolling_dir = tmp_path / "rolling_hourly_chain"
    rolling_dir.mkdir()
    (rolling_dir / "executed_day_accounting.json").write_text(
        json.dumps(
            {
                "bess_terminal_soc_by_depot": {
                    "tsurumaki": {
                        "policy": "fixed_target",
                        "terminal_soc_kwh": 300.0,
                        "balanced": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert runner._bess_terminal_soc(tmp_path) == 300.0


def test_zero_metric_gate_is_fail_closed_for_missing_or_invalid_values() -> None:
    runner = _load_runner()

    assert runner._is_present_zero_metric({"violations": 0}, "violations")
    assert not runner._is_present_zero_metric({}, "violations")
    assert not runner._is_present_zero_metric(
        {"violations": None},
        "violations",
    )
    assert not runner._is_present_zero_metric(
        {"violations": "not-a-number"},
        "violations",
    )
    assert not runner._is_present_zero_metric(
        {"violations": 1},
        "violations",
    )


def test_integer_gate_conversion_preserves_valid_zero() -> None:
    runner = _load_runner()

    assert runner._integer_preserving_zero(0, default=-1) == 0
    assert runner._integer_preserving_zero("0", default=-1) == 0
    assert runner._integer_preserving_zero(None, default=-1) == -1


def test_claim_artifact_gate_accepts_certified_gap_pass_with_scope_blocker() -> None:
    runner = _load_runner()
    classification = {
        "label": "feasible_candidate",
        "mip_gap_target_met": True,
        "certified_mip_gap": 0.03284,
        "optimality_blocking_reasons": [
            "not_an_integrated_global_assignment_and_charging_milp"
        ],
        "interpretation": (
            "A physically feasible incumbent meeting the certified Stage 1 "
            "MIP gap target; integrated global-optimum claims remain blocked."
        ),
    }

    assert runner._claim_artifacts_consistent(
        settings={"mip_gap_target_met": True},
        optimization_result={"result_claim_classification": classification},
        terminal_response={
            "status": "completed",
            "message": (
                "Feasible candidate complete; physical checks and the "
                "certified Stage 1 MIP gap target passed, but integrated "
                "global optimality is not established."
            ),
        },
    )


def test_claim_artifact_gate_accepts_real_gap_miss() -> None:
    runner = _load_runner()
    classification = {
        "label": "feasible_candidate",
        "mip_gap_target_met": False,
        "certified_mip_gap": 0.12,
        "optimality_blocking_reasons": [
            "requested_mip_gap_not_met",
            "not_an_integrated_global_assignment_and_charging_milp",
        ],
        "interpretation": (
            "A physically feasible incumbent; do not describe it as meeting "
            "the requested MIP gap."
        ),
    }

    assert runner._claim_artifacts_consistent(
        settings={"mip_gap_target_met": False},
        optimization_result={"result_claim_classification": classification},
        terminal_response={
            "status": "completed",
            "message": (
                "Feasible candidate complete; physical checks passed, but "
                "the requested MIP gap and integrated global optimality are "
                "not established."
            ),
        },
    )


def test_claim_artifact_gate_rejects_gap_pass_reported_as_gap_miss() -> None:
    runner = _load_runner()

    assert not runner._claim_artifacts_consistent(
        settings={"mip_gap_target_met": True},
        optimization_result={
            "result_claim_classification": {
                "label": "feasible_candidate",
                "mip_gap_target_met": True,
                "certified_mip_gap": 0.03284,
                "optimality_blocking_reasons": [
                    "not_an_integrated_global_assignment_and_charging_milp"
                ],
                "interpretation": (
                    "A physically feasible incumbent; do not describe it as "
                    "meeting the requested MIP gap."
                ),
            }
        },
        terminal_response={
            "status": "completed",
            "message": (
                "Feasible candidate complete; physical checks passed, but "
                "global optimality or the requested MIP gap is not "
                "established."
            ),
        },
    )
