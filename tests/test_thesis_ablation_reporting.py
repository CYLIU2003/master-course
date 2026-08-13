from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from bff.services.optimization_run.thesis_ablation_reporting import (
    comparison_effect_rows,
    method_reporting_rows,
    render_comparison_markdown,
    validate_ready_comparison,
)
from scripts import build_thesis_ablation_comparison as reporting_script


def _method(
    method_id: str,
    *,
    bev_buses: int,
    ice_buses: int,
    bev_trips: int,
    total_cost_jpy: float,
    total_co2_kg: float,
    grid_import_kwh: float,
    pv_to_bus_kwh: float,
    pv_to_bess_kwh: float,
    bess_to_bus_kwh: float,
) -> dict:
    return {
        "method_id": method_id,
        "label": f"Method {method_id}",
        "day_ahead_comparison_eligible": True,
        "used_bev_count": bev_buses,
        "used_ice_count": ice_buses,
        "bev_trip_count": bev_trips,
        "ice_trip_count": 264 - bev_trips,
        "cost_breakdown": {
            "total_cost": total_cost_jpy,
            "total_co2_kg": total_co2_kg,
            "grid_import_kwh": grid_import_kwh,
            "pv_used_total_kwh": pv_to_bus_kwh + pv_to_bess_kwh,
            "pv_to_bus_kwh": pv_to_bus_kwh,
            "pv_to_bess_kwh": pv_to_bess_kwh,
            "bess_to_bus_kwh": bess_to_bus_kwh,
        },
    }


def _ready_payload() -> dict:
    payload = {
        "status": "READY_FOR_DAY_AHEAD_METHOD_COMPARISON",
        "research_conclusion_eligible": True,
        "comparison_scope": "same_canonical_problem_day_ahead",
        "rolling_costs_mixed_into_comparison": False,
        "git_sha": "source-run-git-sha",
        "prepared_input_id": "prepared-1",
        "prepared_source_sha256": "prepared-source-sha",
        "canonical_ablation_input_sha256": "canonical-input-sha",
        "methods": [
            _method(
                "M0",
                bev_buses=13,
                ice_buses=19,
                bev_trips=44,
                total_cost_jpy=1_000.0,
                total_co2_kg=100.0,
                grid_import_kwh=100.0,
                pv_to_bus_kwh=0.0,
                pv_to_bess_kwh=0.0,
                bess_to_bus_kwh=0.0,
            ),
            _method(
                "M1",
                bev_buses=13,
                ice_buses=19,
                bev_trips=44,
                total_cost_jpy=900.0,
                total_co2_kg=90.0,
                grid_import_kwh=0.0,
                pv_to_bus_kwh=20.0,
                pv_to_bess_kwh=30.0,
                bess_to_bus_kwh=25.0,
            ),
            _method(
                "M2",
                bev_buses=21,
                ice_buses=11,
                bev_trips=91,
                total_cost_jpy=1_100.0,
                total_co2_kg=110.0,
                grid_import_kwh=200.0,
                pv_to_bus_kwh=0.0,
                pv_to_bess_kwh=0.0,
                bess_to_bus_kwh=0.0,
            ),
            _method(
                "M3",
                bev_buses=21,
                ice_buses=11,
                bev_trips=91,
                total_cost_jpy=800.0,
                total_co2_kg=70.0,
                grid_import_kwh=20.0,
                pv_to_bus_kwh=40.0,
                pv_to_bess_kwh=60.0,
                bess_to_bus_kwh=50.0,
            ),
        ],
    }
    payload["payload_sha256"] = _payload_sha(payload)
    return payload


def _payload_sha(payload: dict) -> str:
    unsigned = dict(payload)
    unsigned.pop("payload_sha256", None)
    return sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_reporting_rows_preserve_predeclared_method_contrasts() -> None:
    payload = _ready_payload()

    method_rows = method_reporting_rows(payload)
    effects = {
        row["effect_id"]: row for row in comparison_effect_rows(payload)
    }
    markdown = render_comparison_markdown(
        payload,
        method_rows=method_rows,
        effect_rows=list(effects.values()),
    )

    assert [row["method_id"] for row in method_rows] == ["M0", "M1", "M2", "M3"]
    assert effects["M0_TO_M1"]["delta_total_cost_jpy"] == pytest.approx(-100.0)
    assert effects["M2_TO_M3"]["delta_total_co2_kg"] == pytest.approx(-40.0)
    assert effects["M1_TO_M3"]["delta_bev_trip_count"] == 47
    assert effects["M0_TO_M3"]["delta_total_cost_percent"] == pytest.approx(-20.0)
    assert "Rolling costs are excluded" in markdown
    assert "M0 -> M3" in markdown


def test_reporting_rejects_tampering_and_reordered_methods() -> None:
    tampered = _ready_payload()
    tampered["methods"][3]["cost_breakdown"]["total_cost"] = 1.0
    with pytest.raises(ValueError, match="SHA-256"):
        validate_ready_comparison(tampered)

    reordered = _ready_payload()
    reordered["methods"][0], reordered["methods"][1] = (
        reordered["methods"][1],
        reordered["methods"][0],
    )
    reordered["payload_sha256"] = _payload_sha(reordered)
    with pytest.raises(ValueError, match="ordered M0--M3"):
        validate_ready_comparison(reordered)


def test_reporting_bundle_records_clean_builder_and_artifact_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _ready_payload()
    comparison_json = tmp_path / "day_ahead_method_comparison.json"
    comparison_csv = tmp_path / "day_ahead_method_comparison.csv"
    comparison_json.write_text(json.dumps(payload), encoding="utf-8")
    comparison_csv.write_text("method_id\nM0\nM1\nM2\nM3\n", encoding="utf-8")
    monkeypatch.setattr(
        reporting_script,
        "collect_git_state",
        lambda **_: {
            "git_state_available": True,
            "git_dirty": False,
            "git_sha": "a" * 40,
        },
    )

    report_dir = reporting_script._write_reporting_artifacts(
        payload,
        output_dir=tmp_path,
        comparison_json_path=comparison_json,
        comparison_csv_path=comparison_csv,
    )

    assert report_dir is not None
    assert report_dir.name == f"{payload['payload_sha256'][:16]}-{'a' * 12}"
    expected = {
        "method_results.csv",
        "method_effects.csv",
        "method_comparison_report.md",
        "m0_m3_cost_co2_effects.png",
        "m0_m3_cost_co2_effects.svg",
        "m0_m3_dispatch_energy.png",
        "m0_m3_dispatch_energy.svg",
        "reporting_manifest.json",
    }
    assert expected == {path.name for path in report_dir.iterdir()}
    manifest = json.loads(
        (report_dir / "reporting_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "READY"
    assert manifest["source_run_git_sha"] == "source-run-git-sha"
    assert manifest["report_builder_git_sha"] == "a" * 40
    assert manifest["report_builder_git_dirty"] is False
    assert len(manifest["artifacts"]) == 9
    assert all(
        artifact["size_bytes"] > 0 and len(artifact["sha256"]) == 64
        for artifact in manifest["artifacts"].values()
    )

    first_manifest = (report_dir / "reporting_manifest.json").read_bytes()
    rerun_dir = reporting_script._write_reporting_artifacts(
        payload,
        output_dir=tmp_path,
        comparison_json_path=comparison_json,
        comparison_csv_path=comparison_csv,
    )
    assert rerun_dir == report_dir
    assert (report_dir / "reporting_manifest.json").read_bytes() == first_manifest
