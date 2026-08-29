from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from scripts import capture_thesis_weather_parameter_sources as capture


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLISHED_EVIDENCE = (
    REPO_ROOT / "docs" / "evidence" / "weather_dispatch_rerun_bb0c005"
)
PARAMETER_SOURCES = (
    REPO_ROOT / "docs" / "evidence" / "weather_dispatch_rerun_bb0c005_parameter_sources"
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_parameter_source_hash_inventory_matches_exact_bytes() -> None:
    index = _read_json(PARAMETER_SOURCES / "artifact_hashes.json")["sha256"]
    actual = {
        path.relative_to(PARAMETER_SOURCES).as_posix(): _sha256(path)
        for path in PARAMETER_SOURCES.rglob("*")
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    assert index == actual


def test_parameter_sources_match_published_fresh_run_provenance() -> None:
    published = _read_json(PUBLISHED_EVIDENCE / "result_summary.json")
    captured = _read_json(PARAMETER_SOURCES / "parameter_source_manifest.json")

    assert captured["schema_version"] == capture.SCHEMA_VERSION
    assert captured["status"] == "PASS_EXACT_PARAMETER_SOURCE_CAPTURE"
    assert captured["execution_git_sha"] == capture.EXECUTION_SHA
    for code in ("SUNNY", "RAIN"):
        scenario_root = PARAMETER_SOURCES / code
        snapshot_path = scenario_root / "scenario_input_snapshot.json"
        run_manifest_path = scenario_root / "run_input_manifest.json"
        snapshot = _read_json(snapshot_path)
        run_manifest = _read_json(run_manifest_path)
        summary = published["scenarios"][code]
        evidence = captured["scenarios"][code]

        assert snapshot["scenario_id"] == capture.SCENARIO_IDS[code]
        assert run_manifest["scenario_id"] == capture.SCENARIO_IDS[code]
        assert run_manifest["prepared_input_id"] == summary["prepared_input_id"]
        assert run_manifest["prepared_source_sha256"] == summary["prepared_input_sha256"]
        assert run_manifest["git_sha"] == capture.EXECUTION_SHA
        assert run_manifest["git_dirty"] is False
        assert _sha256(snapshot_path) == evidence["scenario_input_snapshot_sha256"]
        assert _sha256(run_manifest_path) == evidence["run_input_manifest_sha256"]
        assert run_manifest["artifacts"]["scenario_input_snapshot.json"]["sha256"] == _sha256(snapshot_path)
        assert run_manifest["artifacts"]["scenario_input_snapshot.json"]["size_bytes"] == snapshot_path.stat().st_size
        assert capture.extract_parameter_values(snapshot) == evidence["parameters"]


def test_parameter_sources_preserve_complete_shared_energy_assets() -> None:
    captured = _read_json(PARAMETER_SOURCES / "parameter_source_manifest.json")
    expected = {
        "grid_import_limit_kw": 200.0,
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
    }
    assert captured["shared_parameters"] == expected
    assert captured["scenarios"]["SUNNY"]["parameters"] == expected
    assert captured["scenarios"]["RAIN"]["parameters"] == expected
