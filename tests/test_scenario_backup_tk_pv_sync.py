from __future__ import annotations

import json
from pathlib import Path

from tools.scenario_backup_tk import (
    _average_monthly_pv_profile_for_depot,
    _merge_selected_depot_pv_assets,
)


def _write_profile(path: Path, *, depot_id: str, day: str, slots: list[float], capacity_kw: float) -> None:
    path.write_text(
        json.dumps(
            {
                "depot_id": depot_id,
                "date": day,
                "slot_minutes": 60,
                "capacity_kw": capacity_kw,
                "pv_generation_kwh_by_slot": slots,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_average_monthly_pv_profile_for_depot_averages_daily_jsons(tmp_path: Path) -> None:
    _write_profile(
        tmp_path / "meguro_2025-08-01_60min.json",
        depot_id="meguro",
        day="2025-08-01",
        slots=[10.0, 20.0],
        capacity_kw=480.8,
    )
    _write_profile(
        tmp_path / "meguro_2025-08-02_60min.json",
        depot_id="meguro",
        day="2025-08-02",
        slots=[14.0, 18.0],
        capacity_kw=480.8,
    )

    profile = _average_monthly_pv_profile_for_depot("meguro", profile_root=tmp_path)

    assert profile is not None
    assert profile["dayCount"] == 2
    assert profile["capacityKw"] == 480.8
    assert profile["pvGenerationKwhBySlot"] == [12.0, 19.0]


def test_merge_selected_depot_pv_assets_preserves_existing_bess_settings(tmp_path: Path) -> None:
    _write_profile(
        tmp_path / "meguro_2025-08-01_60min.json",
        depot_id="meguro",
        day="2025-08-01",
        slots=[4.0, 8.0],
        capacity_kw=480.8,
    )

    merged_rows, synced_ids, missing_ids = _merge_selected_depot_pv_assets(
        ["meguro"],
        [
            {
                "depot_id": "meguro",
                "pv_capacity_kw": 123.0,
                "bess_enabled": True,
                "bess_energy_kwh": 500.0,
            }
        ],
        profile_root=tmp_path,
    )

    assert synced_ids == ["meguro"]
    assert missing_ids == []
    assert merged_rows[0]["depot_id"] == "meguro"
    assert merged_rows[0]["pv_enabled"] is True
    assert merged_rows[0]["pv_capacity_kw"] == 123.0
    assert merged_rows[0]["pv_generation_kwh_by_slot"] == [4.0, 8.0]
    assert merged_rows[0]["bess_enabled"] is True
    assert merged_rows[0]["bess_energy_kwh"] == 500.0
