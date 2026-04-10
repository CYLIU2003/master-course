from __future__ import annotations

import json
from pathlib import Path

from src.optimization.common.solcast_pv_profiles import (
    build_daily_profiles_from_csv,
    export_depot_coordinates,
)


def test_export_depot_coordinates_reads_full_master(tmp_path: Path) -> None:
    out_path = tmp_path / "coords.json"
    payload = export_depot_coordinates(
        master_path=Path("tokyu_bus_depots_master_full.json"),
        output_path=out_path,
    )
    assert payload["count"] >= 10
    assert out_path.exists()

    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(doc.get("coordinates"), list)
    meguro = next((x for x in doc["coordinates"] if x.get("depot_id") == "meguro"), None)
    assert meguro is not None
    assert "lat" in meguro and "lon" in meguro


def test_build_daily_profiles_from_csv_creates_24_slots(tmp_path: Path) -> None:
    csv_path = tmp_path / "meguro_2025_full_60min.csv"
    csv_path.write_text(
        "period_end,period,gti\n"
        "2025-08-01T01:00:00+09:00,PT60M,0\n"
        "2025-08-01T02:00:00+09:00,PT60M,200\n"
        "2025-08-01T03:00:00+09:00,PT60M,500\n",
        encoding="utf-8",
    )

    written = build_daily_profiles_from_csv(
        depot_id="meguro",
        csv_path=csv_path,
        output_dir=tmp_path,
        dates=["2025-08-01"],
        slot_minutes=60,
        timezone_offset="+09:00",
        pv_capacity_kw=100.0,
        fallback_period_min=60,
    )

    assert len(written) == 1
    doc = json.loads(written[0].read_text(encoding="utf-8"))
    assert len(doc["capacity_factor_by_slot"]) == 24
    assert len(doc["pv_generation_kwh_by_slot"]) == 24
    # 02:00 period_end belongs to 01:00-02:00 slot.
    assert doc["capacity_factor_by_slot"][1] == 0.17
    assert doc["pv_generation_kwh_by_slot"][1] == 17.0
    assert doc["performance_ratio"] == 0.85
