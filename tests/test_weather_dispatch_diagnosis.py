from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException
import pytest

import bff.routers.optimization as optimization
import scripts.run_weather_dispatch_diagnosis as diagnosis
from scripts.run_weather_dispatch_diagnosis import (
    REQUIRED_CONFIRMATION_INPUT_HASHES,
    _day_ahead_research_is_accepted,
    _executed_day_total_cost_jpy,
    _normal_confirmation_request,
    _powertrain_selector_is_disabled,
    _rolling_chain_is_accepted,
    assignment_hash_from_rows,
    build_confirmation_input_contract,
    candidate_is_selectable,
    classify_weather_winners,
    confirmation_request_control_payload,
    confirmation_request_matches_worker,
    deduplicate_candidates,
    require_selectable_assignment_coverage,
    select_canonical_candidate,
    selectable_assignment_hashes,
    validate_fixed_dispatch_evidence,
)
from scripts.run_pure_ice_aggregation_weather_ab import ScenarioInput
from bff.routers.optimization import (
    RunOptimizationBody,
    _apply_research_phase3_candidate_coverage_policy,
    _apply_research_phase3_candidate_coverage_policy_or_http_error,
    _prepared_active_bev_count,
    _prepared_active_bev_count_or_http_error,
    _public_run_enforces_interactive_runtime_controls,
    _validate_formal_runtime_controls_or_http_error,
)
from src.optimization.common.evaluator import CostBreakdown
from src.optimization.milp.solver_adapter import (
    _EXACT_ICE_CLONE_REPRESENTATION_OVERRIDE,
    _cost_breakdown_accounting_reconciliation,
    _phase3_candidate_selection_key,
    _stage2_result_accounting_reconciliation,
)


def _assignment(vehicle_id: str, trip_id: str = "trip-1") -> list[dict[str, str]]:
    return [
        {
            "duty_id": f"duty-{vehicle_id}",
            "trip_id": trip_id,
            "vehicle_id": vehicle_id,
            "powertrain": "BEV" if vehicle_id.startswith("bev") else "ICE",
        }
    ]


def _candidate(
    assignment_hash: str,
    cost: float,
    *,
    used_vehicle_count: int = 2,
    proxy: float = 0.0,
    **overrides,
) -> dict:
    candidate = {
        "assignment_hash": assignment_hash,
        "canonical_actual_cost_jpy": cost,
        "used_vehicle_count": used_vehicle_count,
        "stage1_proxy_jpy": proxy,
        "stage2_feasible": True,
        "physical_validation_feasible": True,
        "accounting_reconciliation_passed": True,
        "fallback_used": False,
        "repair_used": False,
        "selectable": True,
    }
    candidate.update(overrides)
    return candidate


def test_selects_minimum_stage2_canonical_cost() -> None:
    selected = select_canonical_candidate(
        [_candidate("expensive", 200.0), _candidate("cheap", 100.0)]
    )
    assert selected["assignment_hash"] == "cheap"


def test_stage1_proxy_order_can_reverse_without_changing_final_selection() -> None:
    selected = select_canonical_candidate(
        [
            _candidate("proxy-best", 200.0, proxy=1.0),
            _candidate("canonical-best", 100.0, proxy=999.0),
        ]
    )
    assert selected["assignment_hash"] == "canonical-best"


def test_classifies_different_weather_winners_as_case_a() -> None:
    verdict = classify_weather_winners(
        [_candidate("sunny-best", 100.0), _candidate("rain-best", 110.0)],
        [_candidate("sunny-best", 120.0), _candidate("rain-best", 90.0)],
        candidate_target=2,
        unique_candidate_count=2,
    )
    assert verdict["case"] == "A"
    assert not verdict["same_selected_assignment"]


def test_classifies_same_weather_winner_as_case_b() -> None:
    verdict = classify_weather_winners(
        [_candidate("same", 100.0), _candidate("other", 110.0)],
        [_candidate("same", 90.0), _candidate("other", 120.0)],
        candidate_target=2,
        unique_candidate_count=2,
    )
    assert verdict["case"] == "B"
    assert verdict["same_selected_assignment"]


def test_fixed_dispatch_evidence_rejects_assignment_change() -> None:
    evidence = validate_fixed_dispatch_evidence(
        requested_assignment_hash="requested",
        solved_assignment_hash="changed",
        sunny_recourse_hash="sun",
        rain_recourse_hash="rain",
    )
    assert evidence["dispatch_reoptimization_performed"] is False
    assert evidence["assignment_unchanged"] is False


def test_fixed_assignment_allows_weather_specific_energy_recourse() -> None:
    evidence = validate_fixed_dispatch_evidence(
        requested_assignment_hash="same",
        solved_assignment_hash="same",
        sunny_recourse_hash="sun",
        rain_recourse_hash="rain",
    )
    assert evidence["energy_recourse_optimization_performed"] is True
    assert evidence["scenario_recourse_can_differ"] is True


def test_assignment_hash_deduplication_uses_physical_assignment() -> None:
    rows = _assignment("bev-1")
    computed = assignment_hash_from_rows(rows)
    unique = deduplicate_candidates(
        [
            {
                "assignment_hash": "source-a",
                "candidate_hash": "a",
                "vehicle_trip_assignments": rows,
                "source_kind": "expanded_discrete_A_search",
            },
            {
                "assignment_hash": "source-b",
                "candidate_hash": "b",
                "vehicle_trip_assignments": list(reversed(rows)),
                "source_kind": "frozen_existing_A_run",
                "source_run_label": "01_A_discrete",
                "candidate_selection_rank": 1,
                "selected": True,
            },
        ]
    )
    assert len(unique) == 1
    assert unique[0]["assignment_hash"] == computed
    assert len(unique[0]["provenance"]) == 2
    assert unique[0]["provenance"][1] == {
        "source_kind": "frozen_existing_A_run",
        "scenario": None,
        "run_dir": None,
        "run_label": "01_A_discrete",
        "candidate_index": None,
        "candidate_hash": "b",
        "selected": True,
        "selection_rank": 1,
        "rejection_reason": None,
    }


def test_physical_assignment_hash_ignores_duty_labels() -> None:
    first = _assignment("bev-1")
    relabelled = [{**first[0], "duty_id": "reconstructed-duty"}]

    assert assignment_hash_from_rows(first) == assignment_hash_from_rows(relabelled)


def test_physical_assignment_hash_matches_production_tuple_order() -> None:
    rows = [
        *_assignment("bev-b", "trip-a"),
        *_assignment("bev-a", "trip-b"),
    ]

    assert assignment_hash_from_rows(rows) == diagnosis._canonical_hash(
        [("bev-a", "trip-b"), ("bev-b", "trip-a")]
    )


def test_physical_assignment_hash_rejects_inconsistent_labels() -> None:
    with pytest.raises(ValueError, match="maps to multiple vehicles"):
        assignment_hash_from_rows(
            [
                *_assignment("bev-1", "trip-1"),
                {
                    **_assignment("bev-2", "trip-2")[0],
                    "duty_id": "duty-bev-1",
                },
            ]
        )
    with pytest.raises(ValueError, match="inconsistent powertrain"):
        assignment_hash_from_rows(
            [
                *_assignment("bev-1", "trip-1"),
                {
                    **_assignment("bev-1", "trip-2")[0],
                    "powertrain": "ICE",
                },
            ]
        )


def test_fallback_repair_and_accounting_mismatch_are_not_selectable() -> None:
    assert not candidate_is_selectable(_candidate("fallback", 1.0, fallback_used=True))
    assert not candidate_is_selectable(_candidate("repair", 1.0, repair_used=True))
    assert not candidate_is_selectable(
        _candidate("accounting", 1.0, accounting_reconciliation_passed=False)
    )
    assert not candidate_is_selectable(
        _candidate("missing-cost", 1.0, canonical_actual_cost_jpy=None)
    )
    assert not candidate_is_selectable(_candidate("rejected", 1.0, selectable=False))


def test_confirmation_requires_complete_rolling_and_research_acceptance() -> None:
    rolling_checks = {
        "full_energy_horizon_requested": True,
        "all_steps_feasible": True,
        "expected_step_count_observed": True,
        "executed_day_accounting_eligible": True,
        "day_ahead_git_clean": True,
        "rolling_runner_git_clean": True,
        "day_ahead_and_rolling_git_sha_match": True,
        "day_ahead_assignment_hash_constant": True,
        "gurobi_available": True,
        "no_chain_runtime_error": True,
    }
    assert _rolling_chain_is_accepted(
        {"chain_accepted": True, "acceptance_checks": rolling_checks}
    )
    rolling_checks["executed_day_accounting_eligible"] = False
    assert not _rolling_chain_is_accepted(
        {"chain_accepted": True, "acceptance_checks": rolling_checks}
    )
    assert _day_ahead_research_is_accepted(
        {"solution_validity": {"research_acceptance_status": "ACCEPTED"}}
    )
    assert not _day_ahead_research_is_accepted(
        {"solution_validity": {"research_acceptance_status": "REJECTED"}}
    )


def test_executed_day_cost_is_authoritative_and_reconciled() -> None:
    accounting = {
        "eligible": True,
        "cost_breakdown": {
            "total_cost": 698_598.628643161,
            "total_cost_with_assets": 698_598.628643161,
            "objective_value": 698_598.628643161,
        },
    }
    assert _executed_day_total_cost_jpy(accounting) == pytest.approx(
        698_598.628643161
    )

    accounting["cost_breakdown"]["objective_value"] += 0.01
    with pytest.raises(RuntimeError, match="totals disagree"):
        _executed_day_total_cost_jpy(accounting)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fleet_validation(fleet_hash: str) -> dict:
    return {
        "expected": {"fleet_contract_hash": fleet_hash},
        "observed": {"fleet_contract_hash": fleet_hash},
        "checks": {"fleet_contract_hash": True},
    }


def _seal_existing_bundle(bundle: Path) -> None:
    artifacts = {
        path.relative_to(bundle).as_posix(): diagnosis._sha256_file(path)
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    _write_json(bundle / "artifact_hashes.json", {"sha256": artifacts})


def test_confirmation_input_contract_fails_when_mandatory_baseline_hash_is_missing(
    tmp_path: Path,
) -> None:
    existing_bundle = tmp_path / "existing"
    confirmation = {"scenarios": {}}
    for code in ("SUNNY", "RAIN"):
        _write_json(
            existing_bundle
            / "scenarios"
            / code
            / "runs"
            / "01_A_discrete"
            / "case_metrics.json",
            {
                "provenance": {
                    "input_hashes": {
                        "timetable_hash": "required-timetable-hash"
                    }
                },
                "fleet_contract_validation": _fleet_validation(f"fleet-{code}"),
            },
        )
        confirmation["scenarios"][code] = {
            "prepared_input_id": f"prepared-{code}",
            "service_date": "2025-08-05",
            "prepared_input_sha256": f"prepared-{code}",
            "fleet_contract_hash": f"fleet-{code}",
            "canonical_input_hashes": {},
        }

    _seal_existing_bundle(existing_bundle)
    with pytest.raises(RuntimeError, match="baseline lacks mandatory input hashes"):
        build_confirmation_input_contract(
            output_dir=tmp_path / "out",
            existing_bundle=existing_bundle,
            confirmation_manifest=confirmation,
        )


def test_confirmation_input_contract_fails_when_mandatory_final_hash_is_missing(
    tmp_path: Path,
) -> None:
    existing_bundle = tmp_path / "existing"
    confirmation = {"scenarios": {}}
    for code in ("SUNNY", "RAIN"):
        hashes = {
            key: f"{code}-{key}"
            for key in REQUIRED_CONFIRMATION_INPUT_HASHES
        }
        _write_json(
            existing_bundle
            / "scenarios"
            / code
            / "runs"
            / "01_A_discrete"
            / "case_metrics.json",
            {
                "provenance": {"input_hashes": hashes},
                "fleet_contract_validation": _fleet_validation(
                    hashes["fleet_contract_hash"]
                ),
            },
        )
        confirmation["scenarios"][code] = {
            "prepared_input_id": f"prepared-{code}",
            "service_date": "2025-08-05",
            "prepared_input_sha256": hashes["prepared_input_sha256"],
            "fleet_contract_hash": hashes["fleet_contract_hash"],
            "canonical_input_hashes": {},
        }

    _seal_existing_bundle(existing_bundle)
    with pytest.raises(RuntimeError, match="lacks frozen-A input hashes"):
        build_confirmation_input_contract(
            output_dir=tmp_path / "out",
            existing_bundle=existing_bundle,
            confirmation_manifest=confirmation,
        )


def test_confirmation_input_contract_rejects_changed_fleet_contract(
    tmp_path: Path,
) -> None:
    existing_bundle = tmp_path / "existing"
    confirmation = {"scenarios": {}}
    for code in ("SUNNY", "RAIN"):
        hashes = {key: f"shared-{key}" for key in REQUIRED_CONFIRMATION_INPUT_HASHES}
        hashes["prepared_input_sha256"] = f"prepared-{code}"
        hashes["prepared_source_sha256"] = f"prepared-{code}"
        hashes["pv_profile_sha256"] = f"pv-{code}"
        hashes["pv_hash"] = f"pv-{code}"
        hashes["canonical_ablation_input_sha256"] = f"canonical-{code}"
        hashes["timetable_hash"] = hashes["trip_input_sha256"]
        hashes["vehicle_hash"] = hashes["vehicle_input_sha256"]
        hashes["tariff_hash"] = hashes["price_input_sha256"]
        hashes["objective_hash"] = hashes["objective_weights_sha256"]
        _write_json(
            existing_bundle
            / "scenarios"
            / code
            / "runs"
            / "01_A_discrete"
            / "case_metrics.json",
            {
                "provenance": {"input_hashes": hashes},
                "fleet_contract_validation": _fleet_validation(
                    hashes["fleet_contract_hash"]
                ),
            },
        )
        confirmation["scenarios"][code] = {
            "prepared_input_id": f"prepared-{code}",
            "service_date": "2025-08-05",
            "prepared_input_sha256": hashes["prepared_input_sha256"],
            "fleet_contract_hash": f"changed-fleet-{code}",
            "canonical_input_hashes": {
                key: value
                for key, value in hashes.items()
                if key
                not in {
                    "prepared_input_sha256",
                    "prepared_source_sha256",
                    "fleet_contract_hash",
                    "timetable_hash",
                    "vehicle_hash",
                    "tariff_hash",
                    "objective_hash",
                    "pv_hash",
                }
            },
            "trip_input_hash": hashes["timetable_hash"],
            "vehicle_input_hash": hashes["vehicle_hash"],
        }

    _seal_existing_bundle(existing_bundle)
    with pytest.raises(RuntimeError, match="fleet_contract_hash"):
        build_confirmation_input_contract(
            output_dir=tmp_path / "out",
            existing_bundle=existing_bundle,
            confirmation_manifest=confirmation,
        )

    for scenario in confirmation["scenarios"].values():
        scenario["fleet_contract_hash"] = "shared-fleet_contract_hash"
    confirmation["scenarios"]["RAIN"]["service_date"] = "2025-08-06"
    with pytest.raises(RuntimeError, match="service date drifted"):
        build_confirmation_input_contract(
            output_dir=tmp_path / "out-service-date",
            existing_bundle=existing_bundle,
            confirmation_manifest=confirmation,
        )


def test_finalization_inventory_hashes_submitted_confirmation_requests(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "output"
    existing_bundle = tmp_path / "existing"
    confirmation_dir_name = "normal_confirmation"
    discovery_scenarios: dict[str, dict[str, str]] = {}
    run_dirs: dict[str, Path] = {}

    for name in (
        "candidate_discovery_manifest.json",
        "weather_candidate_union.json",
        "cross_weather_fixed_dispatch_matrix.json",
    ):
        _write_json(output_dir / name, {})
    diagnosis._write_artifact_seal(
        output_dir / "weather_candidate_union.json",
        output_dir / "weather_candidate_union.seal.json",
    )
    diagnosis._write_artifact_seal(
        output_dir / "cross_weather_fixed_dispatch_matrix.json",
        output_dir / "cross_weather_fixed_dispatch_matrix.seal.json",
    )
    for code in ("SUNNY", "RAIN"):
        discovery_run = tmp_path / f"discovery-{code}"
        discovery_scenarios[code] = {"run_dir": str(discovery_run)}
        for name in diagnosis.DISCOVERY_RUN_INPUT_FILES:
            _write_json(discovery_run / name, {"scenario": code})

        run_dir = tmp_path / f"run-{code}"
        run_dirs[code] = run_dir
        for relative_path in diagnosis.CONFIRMATION_RUN_INPUT_FILES:
            _write_json(run_dir / relative_path, {"scenario": code})
        _write_json(
            existing_bundle
            / "scenarios"
            / code
            / "runs"
            / "01_A_discrete"
            / "case_metrics.json",
            {"scenario": code},
        )
        _write_json(
            output_dir
            / confirmation_dir_name
            / "fresh_prepare"
            / "preparation"
            / code
            / "frontend_optimization_request.json",
            {"source": "template", "scenario": code},
        )
        _write_json(
            output_dir
            / confirmation_dir_name
            / code
            / "frontend_optimization_request.json",
            {"source": "submitted", "scenario": code},
        )

    _seal_existing_bundle(existing_bundle)
    _write_json(
        output_dir / "candidate_discovery_manifest.json",
        {"scenarios": discovery_scenarios},
    )
    inventory = diagnosis._finalization_input_artifacts(
        output_dir=output_dir,
        existing_bundle=existing_bundle,
        run_dirs=run_dirs,
        confirmation_dir_name=confirmation_dir_name,
    )
    sunny_request = inventory["artifacts"]["confirmation_request/SUNNY"]
    assert "diagnosis/weather_candidate_union.seal.json" in inventory["artifacts"]
    assert (
        "diagnosis/cross_weather_fixed_dispatch_matrix.seal.json"
        in inventory["artifacts"]
    )
    assert sunny_request["path"] == str(
        (
            output_dir
            / confirmation_dir_name
            / "SUNNY"
            / "frontend_optimization_request.json"
        ).resolve()
    )
    assert sunny_request["sha256"] == diagnosis._sha256_file(
        output_dir
        / confirmation_dir_name
        / "SUNNY"
        / "frontend_optimization_request.json"
    )


def test_all_stage_runs_strict_finalizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "analyze_existing_bundle",
        "discover_candidates",
        "build_candidate_union",
        "cross_evaluate",
    ):
        monkeypatch.setattr(diagnosis, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(
        diagnosis,
        "confirm_normal_runs",
        lambda **kwargs: {
            "scenarios": {
                "SUNNY": {"run_dir": str(tmp_path / "sunny-run")},
                "RAIN": {"run_dir": str(tmp_path / "rain-run")},
            }
        },
    )
    finalized: dict = {}

    def record_finalization(**kwargs) -> None:
        finalized.update(kwargs)

    monkeypatch.setattr(diagnosis, "finalize_normal_confirmation", record_finalization)
    monkeypatch.setattr(diagnosis, "_artifact_hashes", lambda output_dir: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_weather_dispatch_diagnosis.py",
            "--stage",
            "all",
            "--output-dir",
            str(tmp_path / "output"),
        ],
    )

    diagnosis.main()

    assert finalized["sunny_run_dir"] == tmp_path / "sunny-run"
    assert finalized["rain_run_dir"] == tmp_path / "rain-run"


def test_direct_finalization_rejects_unverified_frozen_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnosis, "_assert_clean_sha", lambda *_args: "clean-sha")
    monkeypatch.setattr(
        diagnosis,
        "_verify_existing_bundle",
        lambda _bundle: {
            "indexed_artifact_count": 103,
            "hash_mismatch_count": 1,
            "hash_mismatches": [{"path": "corrupt.json"}],
            "accepted": False,
        },
    )

    with pytest.raises(
        RuntimeError,
        match="hash verification failed before finalization",
    ):
        diagnosis.finalize_normal_confirmation(
            output_dir=tmp_path / "output",
            sunny_run_dir=tmp_path / "sunny",
            rain_run_dir=tmp_path / "rain",
            existing_bundle=tmp_path / "bundle",
        )


def test_direct_finalization_rejects_dirty_checkout_before_evidence_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_bundle = mock.Mock()
    monkeypatch.setattr(diagnosis, "_verify_existing_bundle", verify_bundle)
    monkeypatch.setattr(
        diagnosis,
        "_assert_clean_sha",
        mock.Mock(side_effect=RuntimeError("formal diagnosis requires a clean worktree")),
    )

    with pytest.raises(RuntimeError, match="requires a clean worktree"):
        diagnosis.finalize_normal_confirmation(
            output_dir=tmp_path / "output",
            sunny_run_dir=tmp_path / "sunny",
            rain_run_dir=tmp_path / "rain",
            existing_bundle=tmp_path / "bundle",
        )

    verify_bundle.assert_not_called()


def test_confirmation_rejects_matrix_sha_before_prepare_or_solve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix_path = tmp_path / "cross_weather_fixed_dispatch_matrix.json"
    _write_json(
        matrix_path,
        {
            "evaluation_git_sha": "producer-sha",
            "candidate_discovery_git_sha": "producer-sha",
        },
    )
    diagnosis._write_artifact_seal(
        matrix_path,
        tmp_path / "cross_weather_fixed_dispatch_matrix.seal.json",
    )
    prepare = mock.Mock()
    monkeypatch.setattr(diagnosis, "prepare_fresh_weather_inputs", prepare)
    monkeypatch.setattr(diagnosis, "_assert_clean_sha", lambda *_args: "consumer-sha")

    with pytest.raises(RuntimeError, match="cross-weather matrix Git SHA mismatch"):
        diagnosis.confirm_normal_runs(
            output_dir=tmp_path,
            base_url="http://127.0.0.1:1",
            existing_bundle=tmp_path / "bundle",
        )

    prepare.assert_not_called()


def test_tie_break_is_used_fleet_then_assignment_hash() -> None:
    selected = select_canonical_candidate(
        [
            _candidate("z", 100.0, used_vehicle_count=3),
            _candidate("b", 100.0, used_vehicle_count=2),
            _candidate("a", 100.0, used_vehicle_count=2),
        ]
    )
    assert selected["assignment_hash"] == "a"


def test_production_phase3_tie_break_key_is_cost_then_fleet_then_hash() -> None:
    candidate = (123.5, 7, "abc", 99, object(), object())
    assert _phase3_candidate_selection_key(candidate) == (123.5, 7, "abc")


def test_pure_ice_aggregate_diagnostic_override_remains_off_by_default() -> None:
    assert _EXACT_ICE_CLONE_REPRESENTATION_OVERRIDE.get() is None


def test_formal_phase3_enables_neutral_candidate_coverage_policy() -> None:
    requested = RunOptimizationBody(
        mode="phase3_two_stage",
        research_run=True,
        stage1_stage2_candidate_limit=1,
        stage1_composition_search_radius=0,
        stage1_bev_frontier_enabled=False,
    )
    effective = _apply_research_phase3_candidate_coverage_policy(
        requested,
        available_bev_count=35,
    )
    assert effective.stage1_stage2_candidate_limit == 22
    assert effective.stage1_composition_search_radius == 4
    assert effective.stage1_bev_frontier_enabled is True
    assert effective.stage1_bev_frontier_min_count == 15
    assert effective.stage1_bev_frontier_max_count == 35
    assert requested.stage1_stage2_candidate_limit == 1


def test_nonresearch_phase3_keeps_requested_candidate_controls() -> None:
    requested = RunOptimizationBody(
        mode="phase3_two_stage",
        research_run=False,
        stage1_stage2_candidate_limit=1,
        stage1_composition_search_radius=0,
        stage1_bev_frontier_enabled=False,
    )
    assert _apply_research_phase3_candidate_coverage_policy(requested) is requested


def test_formal_phase3_frontier_is_bounded_by_prepared_active_bev_count() -> None:
    requested = RunOptimizationBody(
        mode="phase3_two_stage",
        research_run=True,
        stage1_bev_frontier_min_count=15,
        stage1_bev_frontier_max_count=35,
    )
    effective = _apply_research_phase3_candidate_coverage_policy(
        requested,
        available_bev_count=8,
    )
    assert effective.stage1_bev_frontier_min_count == 4
    assert effective.stage1_bev_frontier_max_count == 8


def test_formal_phase3_rejects_inverted_requested_frontier() -> None:
    requested = RunOptimizationBody(
        mode="phase3_two_stage",
        research_run=True,
        stage1_bev_frontier_enabled=False,
        stage1_bev_frontier_min_count=50,
        stage1_bev_frontier_max_count=20,
    )

    with pytest.raises(ValueError, match="min_count must be <="):
        _apply_research_phase3_candidate_coverage_policy(
            requested,
            available_bev_count=20,
        )


def test_public_formal_phase3_returns_422_for_inverted_requested_frontier() -> None:
    requested = RunOptimizationBody(
        mode="phase3_two_stage",
        research_run=True,
        stage1_bev_frontier_enabled=False,
        stage1_bev_frontier_min_count=50,
        stage1_bev_frontier_max_count=20,
    )

    with pytest.raises(HTTPException) as exc_info:
        _apply_research_phase3_candidate_coverage_policy_or_http_error(
            requested,
            available_bev_count=20,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["field"] == "stage1_bev_frontier_min_count"


def test_confirmation_compares_every_normalized_request_control() -> None:
    controls = confirmation_request_control_payload({})
    assert {
        "rebuild_dispatch",
        "use_existing_duties",
        "stage1_activation_start_strengthening",
        "stage1_activation_start_strengthening_vehicle_ids",
        "enableWeatherOperationPolicy",
        "weatherProxyForecastPath",
    }.issubset(controls)
    assert "prepared_input_id" not in controls


def test_confirmation_request_parity_uses_worker_raw_body() -> None:
    copied = {"rebuild_dispatch": True, "use_existing_duties": False}
    worker = RunOptimizationBody.model_validate(copied).model_dump()
    assert confirmation_request_matches_worker(copied, worker)
    assert not confirmation_request_matches_worker(
        copied,
        {**worker, "rebuild_dispatch": False},
    )


@pytest.mark.parametrize(
    ("key", "sunny_value", "rain_value"),
    [
        ("stage1_activation_start_strengthening", False, True),
        ("stage1_activation_start_strengthening_vehicle_ids", None, ["ice-1"]),
        ("enableWeatherOperationPolicy", None, True),
        ("weatherProxyForecastPath", None, "rain.json"),
    ],
)
def test_confirmation_detects_every_previously_omitted_model_control(
    key: str,
    sunny_value: object,
    rain_value: object,
) -> None:
    sunny = {"prepared_input_id": "sunny", key: sunny_value}
    rain = {"prepared_input_id": "rain", key: rain_value}
    assert confirmation_request_control_payload(sunny) != (
        confirmation_request_control_payload(rain)
    )


def test_confirmation_allows_only_prepared_input_id_to_differ() -> None:
    sunny = {"prepared_input_id": "sunny"}
    rain = {"prepared_input_id": "rain"}
    assert confirmation_request_control_payload(sunny) == (
        confirmation_request_control_payload(rain)
    )


def _worker_candidate(index: int, *, selectable: bool = True) -> dict:
    assignments = [
        {
            "duty_id": f"duty-{index}-{trip_index}",
            "trip_id": f"trip-{trip_index}",
            "vehicle_id": f"vehicle-{index}-{trip_index}",
            "powertrain": "ICE",
        }
        for trip_index in range(264)
    ]
    return {
        "stage2_actual_canonical_cost_jpy": 100.0 + index,
        "stage2_feasible": True,
        "canonical_evaluation_feasible": True,
        "accounting_reconciliation_passed": True,
        "physical_validation_feasible": True,
        "served_trip_count": 264,
        "unserved_trip_count": 0,
        "fallback_used": False,
        "repair_used": False,
        "selectable": selectable,
        "vehicle_trip_assignments": assignments,
    }


def test_worker_coverage_counts_only_its_fully_selectable_candidates() -> None:
    payload = {
        "candidates": [
            _worker_candidate(index, selectable=index != 11)
            for index in range(12)
        ]
    }
    assert len(diagnosis._worker_selectable_candidate_hashes(payload)) == 11


def test_discovery_artifact_seal_rejects_interstage_tampering(
    tmp_path: Path,
) -> None:
    scenarios = {}
    for code in ("SUNNY", "RAIN"):
        run_dir = tmp_path / code
        for relative_path in diagnosis.DISCOVERY_RUN_INPUT_FILES:
            _write_json(run_dir / relative_path, {"scenario": code})
        scenarios[code] = {
            "run_dir": str(run_dir),
            "sealed_run_artifacts": diagnosis._sealed_discovery_run_artifacts(
                run_dir
            ),
        }
    manifest = {"scenarios": scenarios}
    assert diagnosis._verify_candidate_discovery_artifacts(manifest)[
        "artifact_count"
    ] == 8

    _write_json(
        tmp_path / "SUNNY" / "solver_result.json",
        {"scenario": "SUNNY", "tampered": True},
    )
    with pytest.raises(RuntimeError, match="changed after sealing"):
        diagnosis._verify_candidate_discovery_artifacts(manifest)


def test_selectable_coverage_counts_only_distinct_fully_valid_assignments() -> None:
    rows = [
        {**_candidate(f"valid-{index}", 100.0 + index), "scenario": "SUNNY"}
        for index in range(12)
    ]
    rows.extend(
        [
            {**_candidate("valid-0", 200.0), "scenario": "SUNNY"},
            {
                **_candidate("invalid-accounting", 50.0),
                "scenario": "SUNNY",
                "accounting_reconciliation_passed": False,
            },
            {**_candidate("rain-only", 40.0), "scenario": "RAIN"},
        ]
    )
    assert selectable_assignment_hashes(rows, scenario="SUNNY") == sorted(
        f"valid-{index}" for index in range(12)
    )


def test_selectable_coverage_fails_when_evaluated_rows_are_not_valid() -> None:
    rows = [
        {**_candidate(f"{code}-{index}", 100.0 + index), "scenario": code}
        for code in ("SUNNY", "RAIN")
        for index in range(12)
    ]
    rows[-1]["physical_validation_feasible"] = False

    with pytest.raises(RuntimeError, match="12 distinct fully selectable"):
        require_selectable_assignment_coverage(rows)


def test_frozen_a_candidate_audit_never_follows_unindexed_run_dir(
    tmp_path: Path,
) -> None:
    paths = []
    for code in ("SUNNY", "RAIN"):
        for index in range(5):
            path = (
                tmp_path
                / "scenarios"
                / code
                / "runs"
                / f"{index + 1:02d}_A_discrete"
                / "case_metrics.json"
            )
            _write_json(
                path,
                {
                    "run_dir": str(tmp_path / "unindexed-poison" / code / str(index)),
                    "provenance": {
                        "representation": "discrete",
                        "audit_representation": "discrete",
                    },
                },
            )
            paths.append(path)
    _write_json(
        tmp_path / "artifact_hashes.json",
        {
            "sha256": {
                path.relative_to(tmp_path).as_posix(): diagnosis._sha256_file(path)
                for path in paths
            }
        },
    )
    assert diagnosis._load_existing_a_candidates(tmp_path) == []


def test_candidate_union_rejects_unverified_frozen_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnosis,
        "_verify_existing_bundle",
        lambda _bundle: {"accepted": False, "hash_mismatches": ["tampered"]},
    )

    with pytest.raises(RuntimeError, match="hash verification failed"):
        diagnosis.build_candidate_union(tmp_path / "output", tmp_path / "bundle")


def test_runtime_analysis_ignores_unindexed_case_metrics(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    indexed = (
        bundle
        / "scenarios"
        / "SUNNY"
        / "runs"
        / "01_A_discrete"
        / "case_metrics.json"
    )
    extra = (
        bundle
        / "scenarios"
        / "SUNNY"
        / "runs"
        / "stale_A_discrete"
        / "case_metrics.json"
    )
    _write_json(indexed, {"indexed": True})
    _write_json(extra, {"indexed": False})
    _write_json(
        bundle / "artifact_hashes.json",
        {
            "sha256": {
                indexed.relative_to(bundle).as_posix(): diagnosis._sha256_file(indexed)
            }
        },
    )

    assert diagnosis._indexed_case_metrics_paths(bundle) == [indexed.resolve()]


def test_runtime_row_never_follows_recorded_external_run_dir(tmp_path: Path) -> None:
    poison_run_dir = tmp_path / "must-not-be-read"
    _write_json(
        poison_run_dir / "solver_result.json",
        {"solver_metadata": {"stage1_runtime_seconds": 999999.0}},
    )
    metrics_path = (
        tmp_path / "scenarios" / "SUNNY" / "runs" / "01_A_discrete"
        / "case_metrics.json"
    )
    _write_json(
        metrics_path,
        {
            "run_dir": str(poison_run_dir),
            "provenance": {"representation": "discrete"},
            "timing": {
                "complete_model_build_time_sec": 10.0,
                "total_solver_time_sec": 50.0,
                "cost_stage_solve_time_sec": 5.0,
            },
            "execution": {"parent_observed_wall_time_sec": 80.0},
            "solve_outcome": {
                "solver_status": "TIME_LIMIT",
                "requested_gap_reached_time_sec": None,
            },
            "runtime_control_validation": {
                "required": {"stage1_stage2_candidate_limit": 22}
            },
        },
    )

    row = diagnosis._runtime_row(metrics_path)

    assert row["runtime_source"] == "indexed_case_metrics_only"
    assert row["source_run_dir_recorded_not_followed"] == str(poison_run_dir)
    assert row["stage1_runtime_sec"] == pytest.approx(50.0)
    assert row["stage2_runtime_sec"] == pytest.approx(5.0)
    assert row["candidate_pool_generated"] == 22
    assert row["rolling_runtime_sec"] is None
    assert row["stage1_energy_recourse_enabled"] is None
    assert row["reporting_accounting_artifact_residual_sec"] == pytest.approx(15.0)


@pytest.mark.parametrize(
    ("artifact_name", "seal_name"),
    (
        ("weather_candidate_union.json", "weather_candidate_union.seal.json"),
        (
            "cross_weather_fixed_dispatch_matrix.json",
            "cross_weather_fixed_dispatch_matrix.seal.json",
        ),
    ),
)
def test_derived_stage_handoff_rejects_tampering(
    tmp_path: Path,
    artifact_name: str,
    seal_name: str,
) -> None:
    artifact_path = tmp_path / artifact_name
    seal_path = tmp_path / seal_name
    _write_json(artifact_path, {"accepted": True})
    diagnosis._write_artifact_seal(artifact_path, seal_path)
    _write_json(artifact_path, {"accepted": False})

    with pytest.raises(RuntimeError, match="changed after sealing"):
        diagnosis._verify_artifact_seal(artifact_path, seal_path)


def test_cross_evaluation_rejects_tampered_candidate_union(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    union_path = tmp_path / "weather_candidate_union.json"
    seal_path = tmp_path / "weather_candidate_union.seal.json"
    _write_json(
        union_path,
        {"producer_git_sha": "consumer-sha", "candidates": []},
    )
    diagnosis._write_artifact_seal(union_path, seal_path)
    _write_json(union_path, {"candidates": [{"tampered": True}]})
    monkeypatch.setattr(diagnosis, "_assert_clean_sha", lambda *_args: "sha")

    with pytest.raises(RuntimeError, match="changed after sealing"):
        diagnosis.cross_evaluate(tmp_path)


def test_cross_evaluation_rejects_discovery_from_another_git_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    union_path = tmp_path / "weather_candidate_union.json"
    _write_json(
        union_path,
        {"producer_git_sha": "consumer-sha", "candidates": []},
    )
    diagnosis._write_artifact_seal(
        union_path,
        tmp_path / "weather_candidate_union.seal.json",
    )
    _write_json(
        tmp_path / "candidate_discovery_manifest.json",
        {"git_sha": "producer-sha"},
    )
    monkeypatch.setattr(
        diagnosis,
        "_assert_clean_sha",
        lambda *_args: "consumer-sha",
    )

    with pytest.raises(RuntimeError, match="candidate discovery Git SHA mismatch"):
        diagnosis.cross_evaluate(tmp_path)


def test_cross_evaluation_rejects_union_from_another_git_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    union_path = tmp_path / "weather_candidate_union.json"
    _write_json(
        union_path,
        {"producer_git_sha": "producer-sha", "candidates": []},
    )
    diagnosis._write_artifact_seal(
        union_path,
        tmp_path / "weather_candidate_union.seal.json",
    )
    monkeypatch.setattr(
        diagnosis,
        "_assert_clean_sha",
        lambda *_args: "consumer-sha",
    )

    with pytest.raises(RuntimeError, match="candidate union Git SHA mismatch"):
        diagnosis.cross_evaluate(tmp_path)


def test_case_a_audit_rejects_tampered_fixed_dispatch_matrix(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "candidate_discovery_manifest.json", {})
    union_path = tmp_path / "weather_candidate_union.json"
    _write_json(union_path, {"candidates": []})
    diagnosis._write_artifact_seal(
        union_path,
        tmp_path / "weather_candidate_union.seal.json",
    )
    matrix_path = tmp_path / "cross_weather_fixed_dispatch_matrix.json"
    _write_json(matrix_path, {"rows": []})
    diagnosis._write_artifact_seal(
        matrix_path,
        tmp_path / "cross_weather_fixed_dispatch_matrix.seal.json",
    )
    _write_json(matrix_path, {"rows": [{"tampered": True}]})

    with pytest.raises(RuntimeError, match="changed after sealing"):
        diagnosis.build_case_a_candidate_selection_audit(
            output_dir=tmp_path,
            confirmation_manifest={},
        )


def test_prepared_active_bev_count_uses_exact_materialized_vehicle_set(
    tmp_path: Path,
) -> None:
    solver_input = tmp_path / "solver_input.json"
    _write_json(
        solver_input,
        {
            "depot_ids": ["dep-1"],
            "vehicles": [
                {
                    "id": "bev-1",
                    "depotId": "dep-1",
                    "type": "BEV",
                    "powertrain": "BEV",
                    "available": True,
                    "batteryKwh": 314.0,
                    "energyConsumption": 1.316,
                    "initialSoc": 0.5,
                    "chargePowerKw": 90.0,
                    "compatibleChargerIds": ["charger-1"],
                },
                {
                    "id": "bev-2",
                    "depotId": "dep-1",
                    "type": "BEV",
                    "powertrainType": "bev",
                    "enabled": True,
                    "batteryKwh": 314.0,
                    "energyConsumption": 1.316,
                    "initialSoc": 0.5,
                    "chargePowerKw": 90.0,
                    "compatibleChargerIds": ["charger-1"],
                },
                {
                    "id": "bev-disabled",
                    "depotId": "dep-1",
                    "powertrain": "BEV",
                    "available": False,
                },
                {
                    "id": "bev-other-depot",
                    "depotId": "dep-2",
                    "powertrain": "BEV",
                    "available": True,
                },
                {
                    "id": "ice-1",
                    "depotId": "dep-1",
                    "type": "ICE",
                    "vehicleType": "ICE",
                    "available": True,
                    "fuelTankL": 160.0,
                    "fuelConsumptionLPerKm": 0.22,
                    "initialFuelL": 144.0,
                },
            ]
        },
    )
    assert _prepared_active_bev_count(solver_input) == 2


def test_prepared_active_bev_count_is_scoped_to_requested_depot(
    tmp_path: Path,
) -> None:
    solver_input = tmp_path / "solver_input.json"
    vehicles = []
    for depot_id, count in (("dep-1", 2), ("dep-2", 1)):
        for index in range(count):
            vehicles.append(
                {
                    "id": f"{depot_id}-bev-{index}",
                    "depotId": depot_id,
                    "type": "BEV",
                    "powertrain": "BEV",
                    "available": True,
                    "batteryKwh": 314.0,
                    "energyConsumption": 1.316,
                    "initialSoc": 0.5,
                    "chargePowerKw": 90.0,
                    "compatibleChargerIds": [f"{depot_id}-charger"],
                }
            )
    _write_json(
        solver_input,
        {"depot_ids": ["dep-1", "dep-2"], "vehicles": vehicles},
    )

    assert _prepared_active_bev_count(solver_input, depot_id="dep-1") == 2
    assert _prepared_active_bev_count(solver_input, depot_id="dep-2") == 1


def test_candidate_accounting_reconciliation_recomputes_all_components() -> None:
    breakdown = CostBreakdown(
        electricity_cost=1.0,
        fuel_cost=2.0,
        demand_cost=3.0,
        contract_overage_cost=4.0,
        vehicle_cost=5.0,
        vehicle_usage_cost=6.0,
        driver_cost=7.0,
        unserved_penalty=8.0,
        switch_cost=9.0,
        degradation_cost=10.0,
        deviation_cost=11.0,
        co2_cost=12.0,
        total_cost=78.0,
    )
    recomputed, delta, passed = _cost_breakdown_accounting_reconciliation(
        breakdown
    )
    assert recomputed == pytest.approx(78.0)
    assert delta == pytest.approx(0.0)
    assert passed is True

    tampered = CostBreakdown(electricity_cost=1.0, total_cost=2.0)
    recomputed, delta, passed = _cost_breakdown_accounting_reconciliation(
        tampered
    )
    assert recomputed == pytest.approx(1.0)
    assert delta == pytest.approx(-1.0)
    assert passed is False


def test_candidate_accounting_reconciles_independent_stage2_result() -> None:
    breakdown = CostBreakdown(
        electricity_cost=30.0,
        fuel_cost=20.0,
        vehicle_usage_cost=100.0,
        co2_cost=10.0,
        total_co2_kg=10.0,
        grid_electricity_co2_kg=4.0,
        total_cost=160.0,
    )
    total, delta, passed = _stage2_result_accounting_reconciliation(
        breakdown,
        stage2_objective_jpy=34.0,
    )
    assert total == pytest.approx(160.0)
    assert delta == pytest.approx(0.0)
    assert passed is True

    total, delta, passed = _stage2_result_accounting_reconciliation(
        breakdown,
        stage2_objective_jpy=35.0,
    )
    assert total == pytest.approx(161.0)
    assert delta == pytest.approx(1.0)
    assert passed is False

    with_leftover = CostBreakdown(
        electricity_cost=35.0,
        electricity_cost_provisional_leftover=5.0,
        fuel_cost=20.0,
        vehicle_usage_cost=100.0,
        co2_cost=10.0,
        total_co2_kg=10.0,
        grid_electricity_co2_kg=4.0,
        total_cost=165.0,
    )
    total, delta, passed = _stage2_result_accounting_reconciliation(
        with_leftover,
        stage2_objective_jpy=34.0,
    )
    assert total == pytest.approx(165.0)
    assert delta == pytest.approx(0.0)
    assert passed is True


def test_prepared_active_bev_count_rejects_missing_powertrain(tmp_path: Path) -> None:
    solver_input = tmp_path / "solver_input.json"
    _write_json(
        solver_input,
        {
            "depot_ids": ["dep-1"],
            "vehicles": [
                {"id": "unknown", "depotId": "dep-1", "available": True}
            ],
        },
    )
    with pytest.raises(ValueError, match="formal fleet contract"):
        _prepared_active_bev_count(solver_input)


def test_prepared_active_bev_count_rejects_implicit_availability(
    tmp_path: Path,
) -> None:
    solver_input = tmp_path / "solver_input.json"
    _write_json(
        solver_input,
        {
            "depot_ids": ["dep-1"],
            "vehicles": [
                {
                    "id": "bev-1",
                    "depotId": "dep-1",
                    "type": "BEV",
                    "powertrain": "BEV",
                    "batteryKwh": 314.0,
                    "energyConsumption": 1.316,
                    "initialSoc": 0.5,
                    "chargePowerKw": 90.0,
                    "compatibleChargerIds": ["charger-1"],
                }
            ],
        },
    )
    with pytest.raises(ValueError, match="vehicle availability is required"):
        _prepared_active_bev_count(solver_input)


def test_prepared_fleet_contract_failure_is_public_validation_error(
    tmp_path: Path,
) -> None:
    solver_input = tmp_path / "solver_input.json"
    _write_json(
        solver_input,
        {
            "depot_ids": ["dep-1"],
            "vehicles": [
                {"id": "unknown", "depotId": "dep-1", "available": True}
            ],
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        _prepared_active_bev_count_or_http_error(solver_input)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["field"] == "vehicles"


def test_public_formal_run_preserves_predeclared_runtime_controls() -> None:
    formal = RunOptimizationBody(research_run=True, gurobi_threads=1)
    ordinary = RunOptimizationBody(research_run=False, gurobi_threads=1)
    assert _public_run_enforces_interactive_runtime_controls(formal) is False
    assert _public_run_enforces_interactive_runtime_controls(ordinary) is True


def test_null_formal_thread_control_is_rejected_before_queueing() -> None:
    request = RunOptimizationBody(research_run=True, gurobi_threads=None)

    with pytest.raises(HTTPException) as exc_info:
        _validate_formal_runtime_controls_or_http_error(request)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["field"] == "gurobi_threads"


def test_formal_endpoint_uses_resolved_depot_for_prepared_bev_count(
    tmp_path: Path,
) -> None:
    fake_job = SimpleNamespace(job_id="job-1")
    solver_input = tmp_path / "solver_input.json"
    _write_json(solver_input, {"vehicles": []})
    prep = SimpleNamespace(
        is_valid=True,
        prepared_input_id="prepared-current",
        solver_input_path=str(solver_input),
        scope_summary={"trip_count": 264},
        error=None,
        error_code=None,
    )
    clean_git_state = {
        "git_state_available": True,
        "git_sha": "clean-sha",
        "git_dirty": False,
        "git_state_error": None,
        "status_porcelain": [],
        "repository_root": str(tmp_path),
    }
    with (
        mock.patch.object(optimization, "_require_scenario"),
        mock.patch.object(
            optimization,
            "collect_git_state",
            return_value=clean_git_state,
        ),
        mock.patch.object(
            optimization,
            "_BFF_RUNTIME_GIT_STATE",
            clean_git_state,
        ),
        mock.patch.object(
            optimization.store,
            "get_scenario_document_shallow",
            return_value={},
        ),
        mock.patch.object(
            optimization,
            "get_or_build_run_preparation",
            return_value=prep,
        ),
        mock.patch.object(
            optimization,
            "_resolve_dispatch_scope",
            return_value={"serviceId": "WEEKDAY", "depotId": "dep-1"},
        ) as resolve_scope,
        mock.patch.object(
            optimization,
            "_prepared_active_bev_count_or_http_error",
            return_value=8,
        ) as count_bevs,
        mock.patch.object(
            optimization.job_store,
            "create_job",
            return_value=fake_job,
        ),
        mock.patch.object(optimization.job_store, "update_job"),
        mock.patch.object(
            optimization.job_store,
            "job_to_dict",
            return_value={"job_id": "job-1", "status": "pending"},
        ),
        mock.patch.object(
            optimization,
            "_submit_optimization_job",
            return_value=True,
        ) as submit_job,
    ):
        optimization.run_optimization(
            "scenario-1",
            RunOptimizationBody(
                mode="phase3_two_stage",
                research_run=True,
                gurobi_threads=1,
            ),
            {"built_ready": True, "built_dir": str(tmp_path), "routes_df": None},
        )

    count_bevs.assert_called_once_with(solver_input, depot_id="dep-1")
    assert resolve_scope.call_args_list == [
        mock.call(
            "scenario-1",
            service_id=None,
            depot_id=None,
            persist=False,
        ),
        mock.call(
            "scenario-1",
            service_id="WEEKDAY",
            depot_id="dep-1",
            persist=True,
        ),
    ]
    assert submit_job.call_args.kwargs["args"][9] == "dep-1"


def test_stale_prepared_input_does_not_persist_rejected_scope(
    tmp_path: Path,
) -> None:
    solver_input = tmp_path / "solver_input.json"
    _write_json(solver_input, {"vehicles": []})
    prep = SimpleNamespace(
        is_valid=True,
        prepared_input_id="prepared-current",
        solver_input_path=str(solver_input),
        scope_summary={"trip_count": 264},
        error=None,
        error_code=None,
    )
    with (
        mock.patch.object(optimization, "_require_scenario"),
        mock.patch.object(
            optimization.store,
            "get_scenario_document_shallow",
            return_value={},
        ),
        mock.patch.object(
            optimization,
            "get_or_build_run_preparation",
            return_value=prep,
        ),
        mock.patch.object(
            optimization,
            "_resolve_dispatch_scope",
            return_value={"serviceId": "WEEKDAY", "depotId": "dep-1"},
        ) as resolve_scope,
        mock.patch.object(optimization.job_store, "create_job") as create_job,
    ):
        with pytest.raises(HTTPException) as exc_info:
            optimization.run_optimization(
                "scenario-1",
                RunOptimizationBody(
                    mode="phase3_two_stage",
                    prepared_input_id="prepared-stale",
                    depot_id="dep-1",
                ),
                {"built_ready": True, "built_dir": str(tmp_path), "routes_df": None},
            )

    assert exc_info.value.status_code == 409
    assert resolve_scope.call_args_list == [
        mock.call(
            "scenario-1",
            service_id=None,
            depot_id="dep-1",
            persist=False,
        )
    ]
    create_job.assert_not_called()


def test_stage_handoff_requires_one_clean_git_sha() -> None:
    diagnosis._require_stage_git_sha(
        {"git_sha": "expected"},
        expected_sha="expected",
        fields=("git_sha",),
        stage="discovery",
    )
    with pytest.raises(RuntimeError, match="discovery Git SHA mismatch"):
        diagnosis._require_stage_git_sha(
            {"git_sha": "producer"},
            expected_sha="consumer",
            fields=("git_sha",),
            stage="discovery",
        )


def test_selector_off_gate_uses_request_and_model_build_evidence() -> None:
    request = {"stage1_powertrain_selector_strengthening": False}
    metadata = {"stage1_powertrain_selector_strengthening_enabled": False}
    assert _powertrain_selector_is_disabled(request, metadata)
    assert not _powertrain_selector_is_disabled({}, metadata)
    assert not _powertrain_selector_is_disabled(request, {})


def test_normal_confirmation_keeps_15_minute_internal_timestep(tmp_path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "time_step_min": 15,
                "timestep_min": 15,
                "time_limit_seconds": 585,
                "stage1_time_limit_seconds": 435,
                "stage2_time_limit_seconds": 30,
                "stage1_powertrain_selector_strengthening": False,
                "require_all_available_bevs": False,
                "stage1_best_obj_stop_enabled": False,
                "gurobi_threads": 1,
                "mip_gap": 0.1,
                "random_seed": 42,
                "run_profile": "day_ahead_and_hourly_rolling",
                "run_hourly_rolling": True,
                "rolling_execution_minutes": 60,
            }
        ),
        encoding="utf-8",
    )
    scenario = ScenarioInput(
        code_name="SUNNY",
        scenario_id="scenario",
        prepared_input_id="prepared",
        optimization_request_path=request_path,
    )
    request = _normal_confirmation_request(scenario)
    assert request["time_step_min"] == 15
    assert request["timestep_min"] == 15
    assert request["rolling_execution_minutes"] == 60
    assert request["time_limit_seconds"] == 585
    assert request["stage1_time_limit_seconds"] == 435
    assert request["stage2_time_limit_seconds"] == 30
    assert request["gurobi_threads"] == 1
