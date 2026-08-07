from __future__ import annotations

import ast
import importlib.util
import json
import zipfile
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
        "math",
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
    assert sunny_settings["vehicle_usage_cost_semantics"] == "unclassified"
    assert rain_settings["vehicle_usage_cost_semantics"] == "unclassified"
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


def test_prepare_payload_replaces_inherited_tou_with_uniform_tariff() -> None:
    runner = _load_runner()

    payload = runner.build_prepare_payload(
        depot_id="tsurumaki",
        service_id="WEEKDAY",
        service_date="2025-08-05",
        pv_source_date="2025-08-05",
        comparison_role="baseline",
        grid_energy_price_yen_per_kwh=30.0,
        demand_charge_yen_per_kw=0.0,
    )

    settings = payload["simulation_settings"]
    assert settings["grid_flat_price_per_kwh"] == 30.0
    assert settings["demand_charge_cost_per_kw"] == 0.0
    assert settings["tou_pricing"] == [
        {"start_hour": 0, "end_hour": 24, "price_per_kwh": 30.0}
    ]
    assert "fixed at 30 JPY/kWh for every clock slot" in settings[
        "experiment_notes"
    ]


def test_controlled_pv_asset_retains_rated_output_and_preserves_bess() -> None:
    runner = _load_runner()
    profile, provenance = runner._load_derived_pv_profile(
        depot_id="tsurumaki",
        pv_source_date="2025-08-10",
        timestep_min=60,
    )
    frontend_asset = {
        "depot_id": "tsurumaki",
        "depot_area_m2": 1450.0,
        "usable_area_ratio": 0.35,
        "panel_power_density_kw_m2": 0.2,
        "pv_capacity_kw": 1000.0,
        "pv_capacity_kw_manual_override": True,
        "pv_case_id": "stale-profile",
        "pv_generation_kwh_by_slot": [99.0] * 24,
        "pv_capacity_factor_by_date": [
            {
                "date": "2025-08-05",
                "slot_minutes": 60,
                "capacity_factor_by_slot": [0.99] * 24,
            }
        ],
        "bess_enabled": True,
        "bess_energy_kwh": 6000.0,
        "bess_power_kw": 900.0,
        "bess_initial_soc_kwh": 3000.0,
        "bess_terminal_soc_target_kwh": 3000.0,
    }

    asset, evidence = runner._build_controlled_pv_asset(
        frontend_asset=frontend_asset,
        profile=profile,
        profile_provenance=provenance,
    )

    assert asset["pv_capacity_kw"] == 1000.0
    assert asset["estimated_installable_area_m2"] == 5000.0
    assert asset["estimated_depot_area_from_pv_capacity_m2"] == pytest.approx(
        14285.714286
    )
    assert asset["pv_case_id"] == "tsurumaki_2025-08-10_60min"
    assert asset["pv_profile_dates"] == ["2025-08-10"]
    assert asset["pv_generation_kwh_by_date"] == [
        {
            "date": "2025-08-10",
            "slot_minutes": 60,
            "pv_generation_kwh_by_slot": asset["pv_generation_kwh_by_slot"],
        }
    ]
    assert evidence["frontend_asset_pv_capacity_kw_before"] == 1000.0
    assert evidence["selected_pv_capacity_source"] == "frontend_rated_output"
    assert evidence["pv_generation_kwh"] == pytest.approx(996.2)
    for field, expected in (
        ("bess_enabled", True),
        ("bess_energy_kwh", 6000.0),
        ("bess_power_kw", 900.0),
        ("bess_initial_soc_kwh", 3000.0),
        ("bess_terminal_soc_target_kwh", 3000.0),
    ):
        assert asset[field] == expected


def test_pv_asset_is_attached_from_the_frontend_bootstrap() -> None:
    runner = _load_runner()

    class BootstrapClient:
        def request_json(
            self,
            method: str,
            path: str,
            payload: dict | None = None,
            *,
            timeout_seconds: float = 120.0,
        ) -> tuple[dict, str]:
            assert method == "GET"
            assert path == "/api/scenarios/scenario-1/editor-bootstrap"
            assert payload is None
            assert timeout_seconds == 987.0
            response = {
                "builderDefaults": {
                    "depotEnergyAssets": [
                        {
                            "depot_id": "tsurumaki",
                            "depot_area_m2": 1450.0,
                            "usable_area_ratio": 0.35,
                            "panel_power_density_kw_m2": 0.2,
                            "pv_capacity_kw": 1000.0,
                            "pv_capacity_kw_manual_override": True,
                            "bess_energy_kwh": 600.0,
                        }
                    ]
                }
            }
            return response, json.dumps(response)

    payload, context = runner._attach_controlled_pv_asset_to_prepare_payload(
        client=BootstrapClient(),
        scenario_id="scenario-1",
        prepare_payload=runner.build_prepare_payload(
            depot_id="tsurumaki",
            service_id="WEEKDAY",
            service_date="2025-08-05",
            pv_source_date="2025-08-05",
            comparison_role="baseline",
        ),
        expected_pv_kwh=6056.25,
        timeout_seconds=987.0,
    )

    asset = payload["simulation_settings"]["depot_energy_assets"][0]
    assert asset["pv_capacity_kw"] == 1000.0
    assert sum(asset["pv_generation_kwh_by_slot"]) == pytest.approx(6056.25)
    assert asset["bess_energy_kwh"] == 600.0
    assert context["pv_profile_source"]["pv_profile_id"] == (
        "tsurumaki_2025-08-05_60min"
    )


def test_runner_pv_capacity_argument_overrides_frontend_rated_output() -> None:
    runner = _load_runner()
    profile, provenance = runner._load_derived_pv_profile(
        depot_id="tsurumaki",
        pv_source_date="2025-08-10",
        timestep_min=60,
    )

    asset, evidence = runner._build_controlled_pv_asset(
        frontend_asset={
            "depot_id": "tsurumaki",
            "depot_area_m2": 1450.0,
            "usable_area_ratio": 0.35,
            "panel_power_density_kw_m2": 0.2,
            "pv_capacity_kw": 1000.0,
            "pv_capacity_kw_manual_override": True,
        },
        profile=profile,
        profile_provenance=provenance,
        pv_capacity_kw=750.0,
    )

    assert asset["pv_capacity_kw"] == 750.0
    assert asset["estimated_installable_area_m2"] == 3750.0
    assert evidence["selected_pv_capacity_source"] == "runner_argument"
    assert evidence["pv_generation_kwh"] == pytest.approx(747.15)


def test_cli_requires_explicit_consent_to_override_frontend_pv_capacity() -> None:
    runner = _load_runner()

    with pytest.raises(ValueError, match="replaces the frontend PV rated output"):
        runner._validate_pv_capacity_override_request(
            pv_capacity_kw=101.5,
            allow_frontend_pv_capacity_override=False,
        )

    runner._validate_pv_capacity_override_request(
        pv_capacity_kw=1000.0,
        allow_frontend_pv_capacity_override=True,
    )
    runner._validate_pv_capacity_override_request(
        pv_capacity_kw=None,
        allow_frontend_pv_capacity_override=False,
    )


def test_uniform_tariff_evidence_requires_every_canonical_slot(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    rows = "\n".join(
        f"{time_idx},30.0,0.0" for time_idx in range(24)
    )
    (tmp_path / "simulation_conditions_tou_prices.csv").write_text(
        "time_idx,grid_energy_price_yen_per_kwh,demand_charge_weight\n"
        f"{rows}\n",
        encoding="utf-8",
    )
    condition = runner._uniform_tariff_condition(
        grid_energy_price_yen_per_kwh=30.0,
        demand_charge_yen_per_kw=0.0,
    )

    accepted = runner._uniform_tariff_evidence(
        case_dir=tmp_path,
        tariff_condition=condition,
    )

    assert accepted["accepted"] is True
    assert accepted["observed_grid_energy_prices_yen_per_kwh"] == [30.0]
    assert accepted["observed_demand_charge_weights_yen_per_kw"] == [0.0]

    (tmp_path / "simulation_conditions_tou_prices.csv").write_text(
        "time_idx,grid_energy_price_yen_per_kwh,demand_charge_weight\n"
        f"{rows.replace('12,30.0,0.0', '12,29.0,0.0')}\n",
        encoding="utf-8",
    )
    rejected = runner._uniform_tariff_evidence(
        case_dir=tmp_path,
        tariff_condition=condition,
    )
    assert rejected["accepted"] is False


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


def test_optimization_payload_exposes_frontier_and_integrated_actual_cost() -> None:
    runner = _load_runner()

    frontier = runner.build_optimization_payload(
        "prepared-frontier",
        experiment_case="phase3_bev_frontier",
    )
    assert frontier["mode"] == "phase3_two_stage"
    assert frontier["stage1_bev_frontier_enabled"] is True
    assert frontier["stage1_bev_frontier_min_count"] == 15
    assert frontier["stage1_bev_frontier_max_count"] == 35
    assert frontier["stage1_stage2_candidate_limit"] >= 22

    integrated = runner.build_optimization_payload(
        "prepared-integrated",
        experiment_case="phase4_integrated_actual_cost",
    )
    assert integrated["mode"] == "phase4_integrated"
    assert integrated["integrated_actual_cost_objective"] is True
    assert integrated["time_limit_seconds"] >= 3600
    assert integrated["mip_gap"] == pytest.approx(0.05)
    assert integrated.get("stage1_bev_frontier_enabled", False) is False

    maximum_ev = runner.build_optimization_payload(
        "prepared-maximum-ev",
        experiment_case="phase4_maximum_ev_utilization",
    )
    assert maximum_ev["mode"] == "phase4_integrated"
    assert maximum_ev["integrated_actual_cost_objective"] is False
    assert maximum_ev["integrated_ev_utilization_mode"] == (
        "minimum_ice_fuel_lexicographic"
    )
    assert maximum_ev["integrated_actual_cost_upper_bound_jpy"] is None

    constrained = runner.build_optimization_payload(
        "prepared-cost-constrained-ev",
        experiment_case="phase4_cost_constrained_ev_utilization",
        actual_cost_upper_bound_jpy=101_000.0,
        actual_cost_upper_bound_delta_ratio=0.01,
    )
    assert constrained["integrated_actual_cost_upper_bound_jpy"] == 101_000.0
    assert constrained["integrated_actual_cost_upper_bound_delta_ratio"] == 0.01

    with pytest.raises(ValueError, match="upper bound"):
        runner.build_optimization_payload(
            "prepared-missing-cap",
            experiment_case="phase4_cost_constrained_ev_utilization",
        )


def test_phase4_formal_gate_requires_verified_same_problem_full_warm_start() -> None:
    runner = _load_runner()
    seed_fingerprint = "a" * 64
    seed_audit = {
        "accepted": True,
        "same_canonical_problem": True,
        "seed_exact_trip_set_match": True,
        "seed_stage2_feasible": True,
        "seed_independent_physical_feasible": True,
        "seed_plan_fingerprint": seed_fingerprint,
    }
    start_audit = {
        "applied": True,
        "same_canonical_problem": True,
        "complete_assignment_binary_start": True,
        "complete_charger_binary_start": True,
        "complete_vehicle_soc_start": True,
        "complete_bess_soc_start": True,
        "complete_bess_mode_binary_start": True,
        "physical_energy_trace_start": True,
        "seed_plan_fingerprint": seed_fingerprint,
    }

    assert runner._phase4_warm_start_evidence_valid(
        seed_audit=seed_audit,
        integrated_start_audit=start_audit,
    )
    for key in tuple(seed_audit):
        broken = dict(seed_audit)
        broken[key] = False
        assert not runner._phase4_warm_start_evidence_valid(
            seed_audit=broken,
            integrated_start_audit=start_audit,
        )
    for key in tuple(start_audit):
        broken = dict(start_audit)
        broken[key] = False
        assert not runner._phase4_warm_start_evidence_valid(
            seed_audit=seed_audit,
            integrated_start_audit=broken,
        )


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


def test_zip_directory_preserves_final_completion_audit_bytes(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    output_dir = tmp_path / "formal_pair"
    output_dir.mkdir()
    completion_path = output_dir / "completion_audit.json"
    completion_path.write_text(
        json.dumps(
            {
                "status": "READY",
                "zip_created": True,
                "zip_path": str(Path(f"{output_dir}.zip").resolve()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "execution_log.md").write_text(
        "# Complete\n",
        encoding="utf-8",
    )

    zip_path = runner._zip_directory(output_dir)

    with zipfile.ZipFile(zip_path, "r") as archive:
        archived_completion = archive.read(
            f"{output_dir.name}/completion_audit.json"
        )
        assert archive.testzip() is None
    assert archived_completion == completion_path.read_bytes()
    assert not Path(f"{zip_path}.tmp").exists()
    assert "zip_size_bytes" not in RUNNER_PATH.read_text(encoding="utf-8")
