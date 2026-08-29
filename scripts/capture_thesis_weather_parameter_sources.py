"""Capture exact Prepared-input parameter sources for thesis reporting.

The published review bundle intentionally contains only a compact subset of
the raw run.  This command copies the two exact run-input snapshots and their
provenance manifests into a small Git-trackable supplement, then records the
parameter values and hashes used by the thesis result builder.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "thesis_weather_parameter_sources_v1"
EXECUTION_SHA = "bb0c0050883a91dd86a9e8813ae88d4b6d8c361d"
SCENARIO_IDS = {
    "SUNNY": "771d115b-75b0-49f7-a7f0-25f259a2cd21",
    "RAIN": "b23fd26c-1233-4c73-bb9e-bdb8b1584760",
}
ASSET_FIELDS = (
    "pv_capacity_kw",
    "bess_enabled",
    "bess_energy_kwh",
    "bess_power_kw",
    "bess_initial_soc_kwh",
    "bess_soc_min_kwh",
    "bess_soc_max_kwh",
    "bess_charge_efficiency",
    "bess_discharge_efficiency",
    "bess_terminal_soc_target_kwh",
)


class ParameterSourceError(RuntimeError):
    """Raised when raw Prepared-input provenance is incomplete or inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ParameterSourceError(message)


def _required_field(container: Any, key: str, context: str) -> Any:
    """Read one required mapping field with a domain-specific diagnostic."""

    if not isinstance(container, Mapping):
        raise ParameterSourceError(
            f"{context}: expected object before field {key!r}, got "
            f"{type(container).__name__}"
        )
    if key not in container:
        raise ParameterSourceError(f"{context}: missing required field {key!r}")
    return container[key]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), f"Expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json"
    }


def extract_parameter_values(
    snapshot: Mapping[str, Any],
    *,
    scenario: str = "UNKNOWN",
    source_path: Path | None = None,
) -> dict[str, Any]:
    """Extract effective depot energy parameters from one run-input snapshot."""

    context = f"{scenario}: {source_path or 'scenario_input_snapshot.json'}"
    persisted = _required_field(snapshot, "persisted_scenario", context)
    charger_sites = _required_field(persisted, "charger_sites", context)
    _require(isinstance(charger_sites, list), f"{context}: charger_sites must be a list")
    _require(len(charger_sites) == 1, f"{context}: expected exactly one charger site")
    charger_site = charger_sites[0]
    charger_site_id = _required_field(charger_site, "id", context)
    _require(charger_site_id == "tsurumaki", f"{context}: unexpected charger-site ID")

    chargers = _required_field(persisted, "chargers", context)
    _require(isinstance(chargers, list), f"{context}: chargers must be a list")
    _require(bool(chargers), f"{context}: chargers must not be empty")
    charger_ids = [_required_field(row, "id", context) for row in chargers]
    _require(
        all(isinstance(value, str) and value for value in charger_ids),
        f"{context}: charger IDs must be non-empty strings",
    )
    _require(
        len(charger_ids) == len(set(charger_ids)),
        f"{context}: duplicate charger IDs",
    )
    charger_site_id_values = [
        _required_field(row, "siteId", context) for row in chargers
    ]
    _require(
        all(isinstance(value, str) and value for value in charger_site_id_values),
        f"{context}: charger site IDs must be non-empty strings",
    )
    charger_site_ids = set(charger_site_id_values)
    _require(
        charger_site_ids == {charger_site_id},
        f"{context}: charger site IDs do not match the depot",
    )
    charger_power_values = [
        _required_field(row, "powerKw", context) for row in chargers
    ]
    _require(
        all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > 0.0
            for value in charger_power_values
        ),
        f"{context}: charger ratings must be positive finite numbers",
    )
    charger_power_kw = set(charger_power_values)
    charger_port_values = [
        _required_field(row, "simultaneous_ports", context) for row in chargers
    ]
    _require(
        all(
            isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
            for value in charger_port_values
        ),
        f"{context}: charger port counts must be positive integers",
    )
    charger_ports = set(charger_port_values)
    charger_bidirectional_values = [
        _required_field(row, "bidirectional", context) for row in chargers
    ]
    _require(
        all(isinstance(value, bool) for value in charger_bidirectional_values),
        f"{context}: charger bidirectional settings must be booleans",
    )
    charger_bidirectional = set(charger_bidirectional_values)
    _require(len(charger_power_kw) == 1, f"{context}: charger ratings differ")
    _require(len(charger_ports) == 1, f"{context}: charger port counts differ")
    _require(
        len(charger_bidirectional) == 1,
        f"{context}: charger bidirectional settings differ",
    )

    overlay = _required_field(persisted, "scenario_overlay", context)
    overlay_by_depot = _required_field(overlay, "depot_energy_assets", context)
    overlay_assets = _required_field(overlay_by_depot, charger_site_id, context)
    simulation_config = _required_field(persisted, "simulation_config", context)
    simulation_assets = _required_field(simulation_config, "depot_energy_assets", context)
    _require(isinstance(simulation_assets, list), f"{context}: energy assets must be a list")
    _require(len(simulation_assets) == 1, f"{context}: expected exactly one simulation energy asset")
    simulation_asset = simulation_assets[0]
    _require(
        _required_field(simulation_asset, "depot_id", context) == charger_site_id,
        f"{context}: unexpected energy-asset depot",
    )

    for field in ASSET_FIELDS:
        overlay_value = _required_field(overlay_assets, field, context)
        simulation_value = _required_field(simulation_asset, field, context)
        _require(
            overlay_value == simulation_value,
            f"{context}: overlay/simulation mismatch for {field}",
        )

    return {
        "charger_count": len(chargers),
        "charger_ids": sorted(charger_ids),
        "charger_site_id": charger_site_id,
        "charger_power_kw": next(iter(charger_power_kw)),
        "charger_simultaneous_ports": next(iter(charger_ports)),
        "charger_bidirectional": next(iter(charger_bidirectional)),
        "grid_import_limit_kw": _required_field(
            charger_site, "grid_import_limit_kw", context
        ),
        "contract_demand_limit_kw": _required_field(
            charger_site, "contract_demand_limit_kw", context
        ),
        **{
            field: _required_field(overlay_assets, field, context)
            for field in ASSET_FIELDS
        },
    }


def _capture_one(
    code: str,
    run_dir: Path,
    output_dir: Path,
    published_summary: Mapping[str, Any],
) -> dict[str, Any]:
    source_snapshot = run_dir / "scenario_input_snapshot.json"
    source_manifest = run_dir / "run_input_manifest.json"
    _require(source_snapshot.is_file(), f"{code}: missing {source_snapshot}")
    _require(source_manifest.is_file(), f"{code}: missing {source_manifest}")

    snapshot = _read_json(source_snapshot)
    manifest = _read_json(source_manifest)
    scenarios = _required_field(published_summary, "scenarios", "result_summary.json")
    summary = _required_field(scenarios, code, "result_summary.json")
    snapshot_hash = _sha256(source_snapshot)

    snapshot_scenario_id = _required_field(snapshot, "scenario_id", str(source_snapshot))
    manifest_scenario_id = _required_field(manifest, "scenario_id", str(source_manifest))
    _require(snapshot_scenario_id == SCENARIO_IDS[code], f"{code}: snapshot scenario ID")
    _require(manifest_scenario_id == SCENARIO_IDS[code], f"{code}: manifest scenario ID")
    _require(
        _required_field(manifest, "prepared_input_id", str(source_manifest))
        == _required_field(summary, "prepared_input_id", "result_summary.json"),
        f"{code}: Prepared ID",
    )
    _require(
        _required_field(manifest, "prepared_source_sha256", str(source_manifest))
        == _required_field(summary, "prepared_input_sha256", "result_summary.json"),
        f"{code}: Prepared source SHA",
    )
    _require(_required_field(manifest, "git_sha", str(source_manifest)) == EXECUTION_SHA, f"{code}: execution SHA")
    _require(_required_field(manifest, "git_dirty", str(source_manifest)) is False, f"{code}: dirty execution")
    artifacts = _required_field(manifest, "artifacts", str(source_manifest))
    snapshot_artifact = _required_field(
        artifacts, "scenario_input_snapshot.json", str(source_manifest)
    )
    _require(
        _required_field(snapshot_artifact, "sha256", str(source_manifest)) == snapshot_hash,
        f"{code}: snapshot hash not sealed by run manifest",
    )
    _require(
        _required_field(snapshot_artifact, "size_bytes", str(source_manifest))
        == source_snapshot.stat().st_size,
        f"{code}: snapshot size not sealed by run manifest",
    )

    target_root = output_dir / code
    target_root.mkdir(parents=True, exist_ok=True)
    target_snapshot = target_root / "scenario_input_snapshot.json"
    target_manifest = target_root / "run_input_manifest.json"
    target_snapshot.write_bytes(source_snapshot.read_bytes())
    target_manifest.write_bytes(source_manifest.read_bytes())
    _require(_sha256(target_snapshot) == snapshot_hash, f"{code}: copied snapshot differs")
    _require(_sha256(target_manifest) == _sha256(source_manifest), f"{code}: copied manifest differs")

    parameters = extract_parameter_values(
        snapshot, scenario=code, source_path=source_snapshot
    )
    protocol = _required_field(published_summary, "protocol", "result_summary.json")
    _require(
        parameters["charger_count"]
        == _required_field(protocol, "charger_count", "result_summary.json.protocol"),
        f"{code}: charger count differs from published summary",
    )
    return {
        "scenario_id": snapshot_scenario_id,
        "published_run_directory": _required_field(summary, "run_directory", "result_summary.json"),
        "prepared_input_id": _required_field(manifest, "prepared_input_id", str(source_manifest)),
        "prepared_source_sha256": _required_field(manifest, "prepared_source_sha256", str(source_manifest)),
        "scenario_input_snapshot_sha256": snapshot_hash,
        "scenario_input_snapshot_size_bytes": source_snapshot.stat().st_size,
        "run_input_manifest_sha256": _sha256(source_manifest),
        "parameters": parameters,
    }


def capture_parameter_sources(
    evidence_dir: Path,
    sunny_run_dir: Path,
    rain_run_dir: Path,
    output_dir: Path,
) -> Path:
    """Validate and capture the two exact run-input parameter sources."""

    summary_path = evidence_dir.resolve() / "result_summary.json"
    published_summary = _read_json(summary_path)
    _require(
        _required_field(published_summary, "execution_git_sha", str(summary_path))
        == EXECUTION_SHA,
        "Published result summary execution SHA differs from the capture contract",
    )
    target = output_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    scenarios = {
        "SUNNY": _capture_one("SUNNY", sunny_run_dir.resolve(), target, published_summary),
        "RAIN": _capture_one("RAIN", rain_run_dir.resolve(), target, published_summary),
    }
    _require(
        scenarios["SUNNY"]["parameters"] == scenarios["RAIN"]["parameters"],
        "SUNNY/RAIN fixed energy-asset parameters differ",
    )

    manifest_path = target / "parameter_source_manifest.json"
    manifest_payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_EXACT_PARAMETER_SOURCE_CAPTURE",
        "execution_git_sha": EXECUTION_SHA,
        "source_semantics": (
            "Exact byte copies of scenario_input_snapshot.json and "
            "run_input_manifest.json from the two published fresh runs"
        ),
        "scenarios": scenarios,
        "shared_parameters": scenarios["SUNNY"]["parameters"],
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    hash_path = target / "artifact_hashes.json"
    hash_path.write_text(
        json.dumps(
            {"schema_version": "artifact_hashes_v1", "sha256": _artifact_hashes(target)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--sunny-run-dir", type=Path, required=True)
    parser.add_argument("--rain-run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = capture_parameter_sources(
        args.evidence_dir,
        args.sunny_run_dir,
        args.rain_run_dir,
        args.output_dir,
    )
    print(manifest_path)
    print("PASS_EXACT_PARAMETER_SOURCE_CAPTURE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
