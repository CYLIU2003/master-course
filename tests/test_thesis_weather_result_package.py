from __future__ import annotations

import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image
import pytest

from scripts import build_thesis_weather_result_package as builder


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPO_ROOT / "docs" / "evidence" / "weather_dispatch_rerun_bb0c005"
PARAMETER_SOURCE_ROOT = (
    REPO_ROOT / "docs" / "evidence" / "weather_dispatch_rerun_bb0c005_parameter_sources"
)
EXPECTED_TREE_SHA256 = "c706da7e10bc4e99a06a441f91e1722baa971b41ab936d29db36e650accede5f"
EXPECTED_FIGURE_STEMS = (
    "01_used_vehicle_comparison",
    "02_assigned_trip_comparison",
    "03_executed_day_cost_breakdown",
    "04_pv_bess_grid_energy_balance",
    "05_pv_utilization_and_curtailment",
)
PROHIBITED_PHRASES = ("最適解", "大域最適", "1%以内", "雨天時の実運行")


def _hash_inventory(root: Path) -> dict[str, str]:
    files = [
        (path.relative_to(root).as_posix(), path)
        for path in root.rglob("*")
        if path.is_file()
    ]
    return {
        relative_path: sha256(path.read_bytes()).hexdigest()
        for relative_path, path in sorted(
            files,
            key=lambda item: item[0].casefold(),
        )
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _refresh_evidence_hash_index(evidence: Path) -> None:
    index_path = evidence / "artifact_hashes.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["sha256"] = {
        name: digest
        for name, digest in _hash_inventory(evidence).items()
        if name != "artifact_hashes.json"
    }
    _write_json(index_path, index)


def _refresh_parameter_hash_index(parameter_sources: Path) -> None:
    index_path = parameter_sources / "artifact_hashes.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["sha256"] = {
        name: digest
        for name, digest in _hash_inventory(parameter_sources).items()
        if name != "artifact_hashes.json"
    }
    _write_json(index_path, index)


@pytest.fixture(scope="module")
def generated_packages(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("thesis-weather-package")
    first = root / "first"
    second = root / "second"
    source_before = _hash_inventory(EVIDENCE_ROOT)
    parameter_source_before = _hash_inventory(PARAMETER_SOURCE_ROOT)
    builder.build_package(EVIDENCE_ROOT, first)
    builder.build_package(EVIDENCE_ROOT, second)
    assert _hash_inventory(EVIDENCE_ROOT) == source_before
    assert _hash_inventory(PARAMETER_SOURCE_ROOT) == parameter_source_before
    return first, second


def test_builder_loads_and_validates_both_canonical_scenarios() -> None:
    bundle = builder.load_and_validate_bundle(EVIDENCE_ROOT)

    assert bundle.tree_sha256 == EXPECTED_TREE_SHA256
    assert set(bundle.scenarios) == {"SUNNY", "RAIN"}
    assert bundle.summary["execution_git_sha"] == builder.EXECUTION_SHA
    assert bundle.input_contract["fixed_nonweather_inputs_equal"] is True
    assert bundle.shared_parameters == {
        "charger_count": 10,
        "charger_ids": [f"depot-fast-tsurumaki-{index:03d}" for index in range(1, 11)],
        "charger_site_id": "tsurumaki",
        "charger_power_kw": 90.0,
        "charger_simultaneous_ports": 1,
        "charger_bidirectional": False,
        "grid_import_limit_kw": 200.0,
        "contract_demand_limit_kw": 200.0,
        "pv_capacity_kw": 1000.0,
        "bess_enabled": True,
        "bess_energy_kwh": 6000.0,
        "bess_power_kw": 900.0,
        "bess_initial_soc_kwh": 3000.0,
        "bess_soc_min_kwh": 1200.0,
        "bess_soc_max_kwh": 4800.0,
        "bess_charge_efficiency": 0.95,
        "bess_discharge_efficiency": 0.95,
        "bess_terminal_soc_target_kwh": 3000.0,
        "grid_flat_price_per_kwh": 30.0,
        "demand_charge_cost_per_kw": 0.0,
        "vehicle_usage_cost_jpy_per_used_bus": 20000.0,
        "diesel_price_per_l": 150.0,
        "co2_price_per_kg": 1.0,
    }

    sunny = bundle.scenarios["SUNNY"]
    rain = bundle.scenarios["RAIN"]
    assert sunny.summary["scenario_id"] == builder.SCENARIO_IDS["SUNNY"]
    assert rain.summary["scenario_id"] == builder.SCENARIO_IDS["RAIN"]
    assert sunny.summary["served_trips"] == rain.summary["served_trips"] == 264
    assert sunny.summary["unserved_trips"] == rain.summary["unserved_trips"] == 0
    assert sunny.summary["used_bev"] == 28
    assert sunny.summary["used_ice"] == 4
    assert rain.summary["used_bev"] == 21
    assert rain.summary["used_ice"] == 11
    assert sunny.costs["pv_generated_kwh"] == pytest.approx(6056.25)
    assert rain.costs["pv_generated_kwh"] == pytest.approx(996.2)
    assert sunny.rolling["step_count"] == rain.rolling["step_count"] == 24
    assert sunny.accounting["eligible"] is rain.accounting["eligible"] is True


def test_selected_candidate_evidence_is_reconciled_with_summary(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "weather_dispatch_rerun_bb0c005"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    summary_path = evidence / "result_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["scenarios"]["RAIN"]["day_ahead_selected_cost_jpy"] += 1.0
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: day-ahead selected candidate cost",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_parameter_snapshot_must_match_its_run_manifest_seal(
    tmp_path: Path,
) -> None:
    parameter_sources = tmp_path / "parameter-sources"
    shutil.copytree(PARAMETER_SOURCE_ROOT, parameter_sources)
    snapshot_path = parameter_sources / "RAIN" / "scenario_input_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["review_tamper"] = True
    _write_json(snapshot_path, snapshot)

    manifest_path = parameter_sources / "parameter_source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scenarios"]["RAIN"]["scenario_input_snapshot_sha256"] = sha256(
        snapshot_path.read_bytes()
    ).hexdigest()
    _write_json(manifest_path, manifest)
    _refresh_parameter_hash_index(parameter_sources)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: snapshot hash not sealed by run manifest",
    ):
        builder.load_and_validate_bundle(EVIDENCE_ROOT, parameter_sources)


def test_fleet_contract_hashes_are_recomputed_from_embedded_payload(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "optimization_parameters.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    contract = payload["effective_model_metadata"]["scenario_fleet_contract"]
    contract["active_vehicle_parameters"][0]["vehicle_id"] = "tampered-vehicle"
    _write_json(path, payload)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: active vehicle IDs do not match parameter rows",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_each_accounting_total_reconciles_to_all_canonical_components(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    summary_path = evidence / "result_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for code in ("SUNNY", "RAIN"):
        path = evidence / code / "executed_day_accounting.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in ("total_cost", "total_cost_with_assets", "objective_value"):
            payload["cost_breakdown"][key] += 100.0
        _write_json(path, payload)
        summary["scenarios"][code]["executed_day_cost_jpy"] += 100.0
    _write_json(summary_path, summary)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="SUNNY: total cost component reconciliation",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_standalone_accounting_must_equal_nested_rolling_ledger(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    accounting_path = evidence / "SUNNY" / "executed_day_accounting.json"
    accounting = json.loads(accounting_path.read_text(encoding="utf-8"))
    costs = accounting["cost_breakdown"]
    costs["vehicle_usage_cost"] += 100.0
    for key in ("total_cost", "total_cost_with_assets", "objective_value"):
        costs[key] += 100.0
    _write_json(accounting_path, accounting)

    summary_path = evidence / "result_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["scenarios"]["SUNNY"]["executed_day_cost_jpy"] += 100.0
    _write_json(summary_path, summary)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="SUNNY: standalone accounting differs from Rolling accounting",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_executed_fuel_liters_reconcile_to_summary_and_cost(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    accounting_path = evidence / "RAIN" / "executed_day_accounting.json"
    accounting = json.loads(accounting_path.read_text(encoding="utf-8"))
    accounting["cost_breakdown"]["ice_fuel_consumed_l"] += 1.0
    _write_json(accounting_path, accounting)

    rolling_path = evidence / "RAIN" / "rolling_chain_summary.json"
    rolling = json.loads(rolling_path.read_text(encoding="utf-8"))
    rolling["executed_day_accounting"] = accounting
    _write_json(rolling_path, rolling)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: executed fuel liters",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_minimum_soc_is_recomputed_from_executed_event_timeline(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    summary_path = evidence / "result_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["scenarios"]["RAIN"]["minimum_executed_bev_soc_kwh"] = -999.0
    _write_json(summary_path, summary)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: minimum executed BEV SOC",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("status", "FAILED", "Confirmation manifest gate failed"),
        ("execution_git_dirty", True, "Confirmation execution worktree was dirty"),
        ("finalization_git_sha", "different", "Confirmation finalization SHA mismatch"),
        ("finalization_git_dirty", True, "Confirmation finalization worktree was dirty"),
    ),
)
def test_confirmation_manifest_requires_clean_identical_execution(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    manifest_path = evidence / "confirmation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    _write_json(manifest_path, manifest)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(builder.EvidenceValidationError, match=message):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_effective_tariffs_match_both_scenarios_and_sealed_raw_source(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    optimization_path = evidence / "SUNNY" / "optimization_parameters.json"
    optimization = json.loads(optimization_path.read_text(encoding="utf-8"))
    optimization["effective_problem_scenario"]["diesel_price_yen_per_l"] = 999.0
    _write_json(optimization_path, optimization)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="SUNNY/RAIN effective tariff differs: diesel_price_yen_per_l",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_physical_schedule_artifact_is_validated_directly(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "physical_schedule_validation.json"
    physical = json.loads(path.read_text(encoding="utf-8"))
    physical["accepted"] = False
    physical["status"] = "INVALID"
    physical["failed_checks"] = ["independent_event_schedule_accepted"]
    physical["validation_metrics"]["infeasible_transition_count"] = 1
    _write_json(path, physical)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: physical validation not accepted",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_rolling_acceptance_requires_all_audited_checks(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "rolling_chain_summary.json"
    rolling = json.loads(path.read_text(encoding="utf-8"))
    rolling["all_steps_feasible"] = False
    rolling["acceptance_checks"]["all_steps_feasible"] = False
    rolling["acceptance_rejection_reasons"] = ["all_steps_feasible"]
    _write_json(path, rolling)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: persisted Rolling checks differ from step evidence",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_rolling_acceptance_is_recomputed_from_persisted_steps(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "rolling_chain_summary.json"
    rolling = json.loads(path.read_text(encoding="utf-8"))
    rolling["steps"][0]["feasible"] = False
    _write_json(path, rolling)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: persisted Rolling checks differ from step evidence",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_physical_validation_is_bound_to_rolling_fleet_and_sha(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "physical_schedule_validation.json"
    physical = json.loads(path.read_text(encoding="utf-8"))
    physical["evidence"]["assignment_hash"] = "tampered-assignment"
    physical["evidence"]["scenario_fleet_contract_hash"] = "tampered-fleet"
    physical["evidence"]["day_ahead_git_sha"] = "tampered-sha"
    _write_json(path, physical)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: physical evidence assignment_hash differs from rolling chain",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


@pytest.mark.parametrize(
    "hash_name",
    ("initial_soc_input_hash", "charger_configuration_hash"),
)
def test_physical_validation_binds_all_input_hashes(
    tmp_path: Path,
    hash_name: str,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "physical_schedule_validation.json"
    physical = json.loads(path.read_text(encoding="utf-8"))
    physical["evidence"][hash_name] = "tampered-input-hash"
    _write_json(path, physical)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match=rf"RAIN: physical evidence {hash_name} differs from rolling chain",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


@pytest.mark.parametrize(
    ("relative_path", "field", "expected_message"),
    (
        ("RAIN/rolling_chain_summary.json", "scenario_id", "rolling summary scenario identity"),
        ("RAIN/optimization_parameters.json", "prepared_input_id", "optimization provenance prepared-input identity"),
        ("RAIN/confirmation_gate.json", "service_date", "confirmation gate service-date identity"),
        ("RAIN/summary.json", "scenario_id", "direct solver summary scenario identity"),
        ("result_summary.json", "prepared_input_id", "RAIN: parameter Prepared ID"),
    ),
)
def test_all_identity_bearing_artifacts_match_the_audited_scenario(
    tmp_path: Path,
    relative_path: str,
    field: str,
    expected_message: str,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    target = payload["scenarios"]["RAIN"] if relative_path == "result_summary.json" else payload
    target[field] = "tampered-identity"
    _write_json(path, payload)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(builder.EvidenceValidationError, match=expected_message):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_optimization_control_provenance_is_clean_and_available(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "optimization_parameters.json"
    optimization = json.loads(path.read_text(encoding="utf-8"))
    optimization["code_provenance"]["git_sha"] = "other"
    optimization["code_provenance"]["git_dirty"] = True
    optimization["code_provenance"]["git_state_available"] = False
    optimization["code_provenance"]["git_state_error"] = "unavailable"
    _write_json(path, optimization)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: optimization Git state unavailable",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_confirmation_gate_requires_exact_producer_check_set(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "confirmation_gate.json"
    gate = json.loads(path.read_text(encoding="utf-8"))
    del gate["checks"]["fallback_and_repair_absent"]
    _write_json(path, gate)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: confirmation gate check set is incomplete",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_rolling_rejects_infeasible_stage2_status(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "rolling_chain_summary.json"
    rolling = json.loads(path.read_text(encoding="utf-8"))
    rolling["steps"][0]["stage2_solver_status"] = "infeasible"
    _write_json(path, rolling)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: unacceptable Stage 2 status at Rolling step 0: infeasible",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_rolling_rejects_duplicate_or_skipped_hourly_timestamps(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "rolling_chain_summary.json"
    rolling = json.loads(path.read_text(encoding="utf-8"))
    rolling["steps"][1]["current_time"] = "00:00"
    _write_json(path, rolling)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: Rolling step time sequence differs at step 1",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_rolling_controls_match_frozen_protocol_at_chain_and_step_levels(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "rolling_chain_summary.json"
    rolling = json.loads(path.read_text(encoding="utf-8"))
    rolling["random_seed"] = 999
    for step in rolling["steps"]:
        step["random_seed"] = 999
    _write_json(path, rolling)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: Rolling top-level control random_seed",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_canonical_input_hashes_match_audited_input_contract(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    for code in ("SUNNY", "RAIN"):
        path = evidence / code / "optimization_parameters.json"
        optimization = json.loads(path.read_text(encoding="utf-8"))
        optimization["canonical_input_dimensions"][
            "trip_structure_input_sha256"
        ] = "same-fabricated-digest"
        _write_json(path, optimization)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="SUNNY: canonical input hash differs from audited contract",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_grid_import_reconciles_to_grid_destination_flows(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "RAIN" / "executed_day_accounting.json"
    accounting = json.loads(path.read_text(encoding="utf-8"))
    accounting["cost_breakdown"]["grid_import_kwh"] = 999.0
    _write_json(path, accounting)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: grid import balance",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_rendered_solver_controls_match_confirmation_evidence(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    for code in ("SUNNY", "RAIN"):
        path = evidence / code / "optimization_parameters.json"
        optimization = json.loads(path.read_text(encoding="utf-8"))
        controls = optimization["effective_optimization_config"]
        controls["random_seed"] = 999
        controls["gurobi_threads"] = 8
        _write_json(path, optimization)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="SUNNY: effective solver controls differ from confirmation manifest",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_rendered_gap_and_runtime_match_direct_solver_artifacts(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    path = evidence / "result_summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["scenarios"]["RAIN"]["stage1_certified_gap_ratio"] = 0.0
    summary["scenarios"]["RAIN"]["solve_time_seconds"] = 1.0
    _write_json(path, summary)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: sealed solver-result gap",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_gap_and_runtime_are_anchored_to_the_sealed_solver_result(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, evidence)
    result_summary_path = evidence / "result_summary.json"
    result_summary = json.loads(result_summary_path.read_text(encoding="utf-8"))
    result_summary["scenarios"]["RAIN"]["stage1_certified_gap_ratio"] = 0.0
    result_summary["scenarios"]["RAIN"]["solve_time_seconds"] = 1.0
    _write_json(result_summary_path, result_summary)

    direct_summary_path = evidence / "RAIN" / "summary.json"
    direct_summary = json.loads(direct_summary_path.read_text(encoding="utf-8"))
    direct_summary["stage1_certified_mip_gap_ratio"] = 0.0
    direct_summary["solve_time_seconds"] = 1.0
    _write_json(direct_summary_path, direct_summary)

    metrics_path = evidence / "RAIN" / "solver_metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["achieved_mip_gap"] = 0.0
    metrics["solve_time_seconds"] = 1.0
    metrics["solver_metadata"]["stage1_certified_mip_gap_ratio"] = 0.0
    _write_json(metrics_path, metrics)
    _refresh_evidence_hash_index(evidence)

    with pytest.raises(
        builder.EvidenceValidationError,
        match="RAIN: sealed solver-result gap",
    ):
        builder.load_and_validate_bundle(evidence, PARAMETER_SOURCE_ROOT)


def test_configured_japanese_font_path_fails_closed_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_font = tmp_path / "missing-NotoSansJP.ttf"
    monkeypatch.setenv("THESIS_JAPANESE_FONT_PATH", str(missing_font))

    with pytest.raises(
        builder.EvidenceValidationError,
        match="THESIS_JAPANESE_FONT_PATH is not a file",
    ):
        builder._configure_matplotlib()


def test_configured_japanese_font_path_is_the_selected_face(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matplotlib import font_manager

    configured_font = os.environ.get("THESIS_JAPANESE_FONT_PATH")
    if configured_font:
        configured_path = Path(configured_font).resolve()
    else:
        configured_path = next(
            Path(entry.fname).resolve()
            for entry in font_manager.fontManager.ttflist
            if entry.name == "Noto Sans JP"
        )
    monkeypatch.setenv("THESIS_JAPANESE_FONT_PATH", str(configured_path))

    _plt, font_name = builder._configure_matplotlib()
    selected_path = Path(
        font_manager.findfont(
            font_manager.FontProperties(family=font_name),
            fallback_to_default=False,
        )
    ).resolve()
    assert selected_path == configured_path


def test_reporting_renderer_versions_are_exactly_pinned() -> None:
    assert builder._renderer_versions() == builder.EXPECTED_RENDERER_VERSIONS


def test_generated_package_is_byte_deterministic_and_complete(
    generated_packages: tuple[Path, Path],
) -> None:
    first, second = generated_packages
    assert _hash_inventory(first) == _hash_inventory(second)

    inventory = _hash_inventory(first)
    for stem in EXPECTED_FIGURE_STEMS:
        assert f"{stem}.png" in inventory
        assert f"{stem}.svg" in inventory
    assert not any(name.startswith("06_daily_energy_flow_timeseries") for name in inventory)
    for name in (
        "experiment_parameters.csv",
        "experiment_parameters.md",
        "scenario_results.csv",
        "scenario_results.md",
        "cost_breakdown.csv",
        "cost_breakdown.md",
        "energy_balance.csv",
        "energy_balance.md",
        "thesis_summary_table.csv",
        "thesis_summary_table.md",
        "claim_boundary.md",
        "results_section_ja.md",
        "README.md",
        "package_manifest.json",
    ):
        assert name in inventory


def test_generated_tables_preserve_scenario_parameters_and_results(
    generated_packages: tuple[Path, Path],
) -> None:
    output, _ = generated_packages
    parameters = {
        (row["区分"], row["項目"]): row
        for row in _read_csv(output / "experiment_parameters.csv")
    }
    assert parameters[("運行", "営業所")]["共通値"] == "tsurumaki"
    assert parameters[("運行", "時刻表")]["共通値"] == "WEEKDAY"
    assert parameters[("運行", "運行日")]["共通値"] == "2025-08-05"
    assert parameters[("反実仮想", "気象・PV条件")]["RAIN"] == "2025-08-10由来の低PV曲線"
    assert parameters[("車両", "有効車両数")]["共通値"] == "60"
    assert parameters[("車両", "BEV／ICE在庫")]["共通値"] == "35／25"
    assert parameters[("充電", "充電器数")]["共通値"] == "10"
    assert parameters[("充電", "設置営業所")]["共通値"] == "tsurumaki"
    assert parameters[("充電", "1基あたり定格出力")]["共通値"] == "90"
    assert parameters[("充電", "1基あたり同時充電ポート数")]["共通値"] == "1"
    assert parameters[("充電", "双方向充放電")]["共通値"] == "OFF"
    assert parameters[("充電", "受電上限")]["共通値"] == "200"
    assert parameters[("PV", "PV定格容量")]["共通値"] == "1000"
    assert parameters[("BESS", "定格容量／出力")]["共通値"] == "6000／900"
    assert parameters[("BESS", "SOC許容範囲")]["共通値"] == "1200～4800"
    assert parameters[("BESS", "実行日初期／終端SOC")]["共通値"] == "3000／3000"
    assert parameters[("Solver", "Gurobi threads")]["共通値"] == "1"
    assert parameters[("Solver", "powertrain selector strengthening")]["共通値"] == "OFF"
    assert parameters[("Solver", "候補構成探索radius（実効）")]["共通値"] == "4"
    assert parameters[("Solver", "BEV frontier範囲（実効）")]["共通値"] == "15～35"
    assert "objective_is_actual_cost=false" in parameters[("料金", "評価額の性格")]["共通値"]

    scenarios = {row["scenario"]: row for row in _read_csv(output / "scenario_results.csv")}
    assert scenarios["SUNNY"]["scenario_id"] == builder.SCENARIO_IDS["SUNNY"]
    assert scenarios["RAIN"]["scenario_id"] == builder.SCENARIO_IDS["RAIN"]
    assert scenarios["SUNNY"]["rolling_steps"] == scenarios["RAIN"]["rolling_steps"] == "24/24"
    assert scenarios["SUNNY"]["physical_validation"] == scenarios["RAIN"]["physical_validation"] == "VALID"
    assert float(scenarios["SUNNY"]["rolling_model_evaluation_jpy"]) == pytest.approx(660_983.7838045002)
    assert float(scenarios["RAIN"]["rolling_model_evaluation_jpy"]) == pytest.approx(698_598.6286431606)
    assert float(scenarios["RAIN"]["day_ahead_selected_candidate_cost_jpy"]) == pytest.approx(698_296.4652840658)
    assert float(scenarios["RAIN"]["rolling_minus_day_ahead_jpy"]) == pytest.approx(302.1633590948768)
    assert scenarios["SUNNY"]["minimum_recorded_bev_soc_scope"] == (
        "全BEVの初期状態を含む正本集計値。使用BEVの運行中安全余裕ではない"
    )

    energy = {row["scenario"]: row for row in _read_csv(output / "energy_balance.csv")}
    assert float(energy["SUNNY"]["bess_output_per_pv_input"]) == pytest.approx(0.95**2)
    assert float(energy["RAIN"]["bess_output_per_pv_input"]) == pytest.approx(0.95**2)
    assert energy["SUNNY"]["terminal_energy_balanced"] == energy["RAIN"]["terminal_energy_balanced"] == "ON"


def test_generated_claims_and_figure_metadata_are_bounded(
    generated_packages: tuple[Path, Path],
) -> None:
    output, _ = generated_packages
    textual = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(output.iterdir())
        if path.suffix in {".md", ".csv", ".json", ".svg"}
    )
    for phrase in PROHIBITED_PHRASES:
        assert phrase not in textual
    assert "Stage 1の近似目的関数に対するcertified MIP gap" in textual
    assert "評価した有限候補集合から選択された、物理的・会計的に妥当なPhase 3二段階実行可能解" in textual
    assert "2025-08-05の平日運行へ2025-08-10由来の低PV曲線を与えた反実仮想" in textual
    assert "本モデルの費用定義に基づく24時間Rolling実行日評価額" in textual
    assert "objective_is_actual_cost=false" in textual
    assert "使用BEVの運行中安全余裕ではない" in textual

    results = (output / "results_section_ja.md").read_text(encoding="utf-8")
    compact_length = len("".join(results.split()))
    assert 1200 <= compact_length <= 2000

    manifest = json.loads((output / "package_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS"
    assert manifest["execution_git_sha"] == builder.EXECUTION_SHA
    assert manifest["source_bundle_tree_sha256"] == EXPECTED_TREE_SHA256
    assert manifest["parameter_source_tree_sha256"] == builder.load_and_validate_bundle(
        EVIDENCE_ROOT
    ).parameter_source_tree_sha256
    assert manifest["renderer_versions"] == builder.EXPECTED_RENDERER_VERSIONS
    assert manifest["png_dpi"] == 300
    assert manifest["timeseries_figure_created"] is False
    assert "No complete 96-slot" in manifest["timeseries_figure_omission_reason"]

    for stem in EXPECTED_FIGURE_STEMS:
        assert "<text" not in (output / f"{stem}.svg").read_text(encoding="utf-8")
        with Image.open(output / f"{stem}.png") as image:
            dpi = image.info.get("dpi")
            assert dpi is not None
            assert dpi[0] == pytest.approx(300, abs=0.1)
            assert dpi[1] == pytest.approx(300, abs=0.1)
            assert image.width > 1000
            assert image.height > 900


def test_format_cell_is_finite_plain_decimal_and_normalizes_tiny_values() -> None:
    assert builder._format_cell(1.2345678901234) == "1.234567890123"
    assert builder._format_cell(1.0e-10) == "0"
    assert builder._format_cell(1.0e20) == "100000000000000000000"
    with pytest.raises(builder.EvidenceValidationError, match="Non-finite"):
        builder._format_cell(float("nan"))
    with pytest.raises(builder.EvidenceValidationError, match="Non-finite"):
        builder._format_cell(float("inf"))


def test_tree_hash_is_independent_of_mapping_insertion_order() -> None:
    first = {"z.json": "2", "A.json": "1", "b.json": "3"}
    second = {"b.json": "3", "z.json": "2", "A.json": "1"}
    assert builder._tree_sha256(first) == builder._tree_sha256(second)


def test_bundle_hash_map_uses_relative_posix_casefold_order(tmp_path: Path) -> None:
    for name in ("z.json", "A.json", "b.json"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    assert list(builder._bundle_hashes(tmp_path)) == [
        "A.json",
        "b.json",
        "z.json",
    ]


def test_builder_rejects_stale_preexisting_output(tmp_path: Path) -> None:
    output = tmp_path / "stale"
    builder.build_package(EVIDENCE_ROOT, output)
    (output / "obsolete_result.csv").write_text("stale\n", encoding="utf-8")

    with pytest.raises(builder.EvidenceValidationError, match="Output inventory differs"):
        builder.build_package(EVIDENCE_ROOT, output)


def test_failed_rebuild_leaves_existing_package_byte_exact(
    generated_packages: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _ = generated_packages
    before = _hash_inventory(output)

    def fail_after_tables_are_staged():
        raise builder.EvidenceValidationError("intentional rendering failure")

    monkeypatch.setattr(builder, "_configure_matplotlib", fail_after_tables_are_staged)
    with pytest.raises(builder.EvidenceValidationError, match="rendering failure"):
        builder.build_package(EVIDENCE_ROOT, output, PARAMETER_SOURCE_ROOT)

    assert _hash_inventory(output) == before
    assert not list(output.parent.glob(f".{output.name}.staging-*"))
    assert not list(output.parent.glob(f".{output.name}.backup-*"))


def test_parameter_snapshot_schema_errors_are_domain_specific(tmp_path: Path) -> None:
    snapshot = {"persisted_scenario": {"charger_sites": []}}
    with pytest.raises(
        builder.EvidenceValidationError,
        match=r"SUNNY: .*expected one parameter-source charger site",
    ):
        builder._extract_parameter_values(
            snapshot,
            scenario="SUNNY",
            source_path=tmp_path / "scenario_input_snapshot.json",
        )


def test_committed_package_is_exactly_regenerable() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "verify_thesis_weather_result_package.py"),
            "--evidence-dir",
            str(EVIDENCE_ROOT),
            "--parameter-evidence-dir",
            str(PARAMETER_SOURCE_ROOT),
            "--committed-dir",
            str(REPO_ROOT / "docs" / "thesis" / "weather_results_bb0c005"),
        ],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS_EXACT_THESIS_WEATHER_RESULT_PACKAGE" in completed.stdout
