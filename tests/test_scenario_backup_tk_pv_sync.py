from __future__ import annotations

import json
from pathlib import Path

from tools.scenario_backup_tk import (
    _load_selected_date_pv_profile_for_depot,
    _merge_selected_depot_pv_assets,
    _rebuild_pv_generation_for_row,
)


def _write_profile(
    path: Path,
    *,
    depot_id: str,
    day: str,
    slots: list[float],
    capacity_kw: float,
) -> None:
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


def test_load_selected_date_pv_profile_for_depot_uses_requested_daily_jsons(tmp_path: Path) -> None:
    _write_profile(
        tmp_path / "meguro_2025-08-01_60min.json",
        depot_id="meguro",
        day="2025-08-01",
        slots=[10.0, 20.0],
        capacity_kw=200.0,
    )
    _write_profile(
        tmp_path / "meguro_2025-08-02_60min.json",
        depot_id="meguro",
        day="2025-08-02",
        slots=[14.0, 18.0],
        capacity_kw=200.0,
    )

    profile, missing_dates = _load_selected_date_pv_profile_for_depot(
        "meguro",
        ["2025-08-01", "2025-08-02"],
        current_depot_area_m2=1000.0,
        profile_root=tmp_path,
    )

    assert missing_dates == []
    assert profile is not None
    assert profile["serviceDates"] == ["2025-08-01", "2025-08-02"]
    assert profile["capacityKw"] == 70.0
    assert profile["pvGenerationKwhBySlot"] == [3.5, 7.0, 4.9, 6.3]


def test_merge_selected_depot_pv_assets_preserves_bess_settings_and_scales_by_depot_area(
    tmp_path: Path,
) -> None:
    _write_profile(
        tmp_path / "meguro_2025-08-01_60min.json",
        depot_id="meguro",
        day="2025-08-01",
        slots=[20.0, 40.0],
        capacity_kw=200.0,
    )

    merged_rows, synced_ids, missing_ids = _merge_selected_depot_pv_assets(
        ["meguro"],
        [
            {
                "depot_id": "meguro",
                "depot_area_m2": 1000.0,
                "bess_enabled": True,
                "bess_energy_kwh": 500.0,
            }
        ],
        ["2025-08-01"],
        profile_root=tmp_path,
    )

    assert synced_ids == ["meguro"]
    assert missing_ids == []
    assert merged_rows[0]["depot_id"] == "meguro"
    assert merged_rows[0]["pv_enabled"] is True
    assert merged_rows[0]["pv_capacity_kw"] == 70.0
    assert merged_rows[0]["estimated_installable_area_m2"] == 350.0
    assert merged_rows[0]["pv_generation_kwh_by_slot"] == [7.0, 14.0]
    assert merged_rows[0]["pv_profile_dates"] == ["2025-08-01"]
    assert merged_rows[0]["bess_enabled"] is True
    assert merged_rows[0]["bess_energy_kwh"] == 500.0


def test_rebuild_pv_generation_for_row_recalculates_from_capacity_factor_metadata() -> None:
    row = {
        "depot_area_m2": 1000.0,
        "pv_capacity_factor_by_date": [
            {
                "date": "2025-08-01",
                "slot_minutes": 60,
                "capacity_factor_by_slot": [0.1, 0.3],
            },
            {
                "date": "2025-08-02",
                "slot_minutes": 60,
                "capacity_factor_by_slot": [0.2],
            },
        ],
    }

    rebuilt = _rebuild_pv_generation_for_row(dict(row))

    assert rebuilt["pv_profile_dates"] == ["2025-08-01", "2025-08-02"]
    assert rebuilt["pv_capacity_kw"] == 70.0
    assert rebuilt["pv_generation_kwh_by_slot"] == [7.0, 21.0, 14.0]
    assert rebuilt["pv_generation_kwh_by_date"] == [
        {
            "date": "2025-08-01",
            "slot_minutes": 60,
            "pv_generation_kwh_by_slot": [7.0, 21.0],
        },
        {
            "date": "2025-08-02",
            "slot_minutes": 60,
            "pv_generation_kwh_by_slot": [14.0],
        },
    ]


def test_merge_selected_depot_pv_assets_disables_pv_when_depot_area_missing(
    tmp_path: Path,
) -> None:
    _write_profile(
        tmp_path / "meguro_2025-08-01_60min.json",
        depot_id="meguro",
        day="2025-08-01",
        slots=[20.0, 40.0],
        capacity_kw=200.0,
    )

    merged_rows, synced_ids, missing_ids = _merge_selected_depot_pv_assets(
        ["meguro"],
        [{"depot_id": "meguro", "bess_enabled": True}],
        ["2025-08-01"],
        profile_root=tmp_path,
    )

    assert synced_ids == []
    assert missing_ids == []
    assert merged_rows[0]["pv_enabled"] is False
    assert merged_rows[0]["pv_capacity_kw"] == 0.0
    assert merged_rows[0]["pv_generation_kwh_by_slot"] == []
