"""
tests/test_engine_bus_extractor.py

Unit tests for Phase 1 and Phase 2 of src/engine_bus_extractor.py.

Phase 1 tests use pre-built output JSON (data/engine_bus/output/) to avoid
re-running the Excel extraction on every test run. If the JSON does not exist
(e.g., fresh checkout) the extraction is triggered automatically.

Phase 2 tests exercise select_vehicles() with synthetic fixture data so
they run without any filesystem dependency.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure src/ is importable
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.engine_bus_extractor import (
    build_simulation_library,
    compute_derived,
    normalize_records,
    select_vehicles,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _load_normalized() -> list[dict]:
    """Load pre-built normalized JSON, or run extraction if missing."""
    path = _ROOT / "data" / "engine_bus" / "output" / "engine_bus_normalized.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # Fall back to full extraction (requires constant/ Excel files)
    from src.engine_bus_extractor import run_extraction

    return run_extraction()["normalized"]


def _load_simulation_library() -> list[dict]:
    path = (
        _ROOT / "data" / "engine_bus" / "output" / "engine_bus_simulation_library.json"
    )
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    normalized = _load_normalized()
    return build_simulation_library(normalized)


# Synthetic minimal records for Phase 2 selector tests (no Excel needed)
_SYNTHETIC_RECORDS: list[dict] = [
    {
        "manufacturer": "Hino",
        "model_code": "HINO-R01",
        "bus_category": "route_bus",
        "passenger_capacity": 79,
        "gross_vehicle_weight_kg": 14548,
        "max_power_kW": 191.0,
        "fuel_economy_km_per_L": 5.38,
        "co2_g_per_km": 480.7,
        "diesel_consumption_L_per_km": 1.0 / 5.38,
        "needs_manual_review": False,
    },
    {
        "manufacturer": "Hino",
        "model_code": "HINO-R02",
        "bus_category": "route_bus",
        "passenger_capacity": 65,
        "gross_vehicle_weight_kg": 12000,
        "max_power_kW": 160.0,
        "fuel_economy_km_per_L": 4.36,
        "co2_g_per_km": 593.0,
        "diesel_consumption_L_per_km": 1.0 / 4.36,
        "needs_manual_review": False,
    },
    {
        "manufacturer": "Hino",
        "model_code": "HINO-C01",
        "bus_category": "coach_bus",
        "passenger_capacity": 29,
        "gross_vehicle_weight_kg": 7500,
        "max_power_kW": 110.0,
        "fuel_economy_km_per_L": 9.59,
        "co2_g_per_km": 269.7,
        "diesel_consumption_L_per_km": 1.0 / 9.59,
        "needs_manual_review": False,
    },
    {
        "manufacturer": "Isuzu",
        "model_code": "ISUZU-R01",
        "bus_category": "route_bus",
        "passenger_capacity": 75,
        "gross_vehicle_weight_kg": 13500,
        "max_power_kW": 175.0,
        "fuel_economy_km_per_L": 5.11,
        "co2_g_per_km": 506.0,
        "diesel_consumption_L_per_km": 1.0 / 5.11,
        "needs_manual_review": False,
    },
    {
        "manufacturer": "MitsubishiFuso",
        "model_code": "FUSO-R01",
        "bus_category": "route_bus",
        "passenger_capacity": 79,
        "gross_vehicle_weight_kg": 14800,
        "max_power_kW": 220.0,
        "fuel_economy_km_per_L": 4.16,
        "co2_g_per_km": 621.7,
        "diesel_consumption_L_per_km": 1.0 / 4.16,
        "needs_manual_review": False,
    },
]


# ---------------------------------------------------------------------------
# Phase 1: compute_derived
# ---------------------------------------------------------------------------


class TestComputeDerived:
    def test_diesel_consumption_derived(self) -> None:
        rec = {
            "fuel_economy_km_per_L": 5.0,
            "co2_g_per_km": 500.0,
            "passenger_capacity": 70,
        }
        out = compute_derived(rec)
        assert out["diesel_consumption_L_per_km"] == pytest.approx(0.2, rel=1e-4)
        assert out["diesel_consumption_L_per_100km"] == pytest.approx(20.0, rel=1e-4)

    def test_equivalent_energy(self) -> None:
        rec = {
            "fuel_economy_km_per_L": 5.0,
            "co2_g_per_km": 500.0,
            "passenger_capacity": 70,
        }
        out = compute_derived(rec)
        # 9.8 kWh/L * 0.2 L/km = 1.96 kWh/km
        assert out["equivalent_energy_kWh_per_km"] == pytest.approx(1.96, rel=1e-3)

    def test_consistency_ok(self) -> None:
        rec = {
            "fuel_economy_km_per_L": 4.36,
            "co2_g_per_km": 593.0,
            "passenger_capacity": 79,
        }
        out = compute_derived(rec)
        assert out["consistency_ok"] is True

    def test_none_fuel_economy(self) -> None:
        rec = {
            "fuel_economy_km_per_L": None,
            "co2_g_per_km": 500.0,
            "passenger_capacity": 70,
        }
        out = compute_derived(rec)
        assert out["diesel_consumption_L_per_km"] is None

    def test_per_pax_indicators(self) -> None:
        rec = {
            "fuel_economy_km_per_L": 5.0,
            "co2_g_per_km": 500.0,
            "passenger_capacity": 50,
        }
        out = compute_derived(rec)
        assert out["co2_g_per_pax_km"] == pytest.approx(10.0, rel=1e-4)
        assert out["diesel_L_per_pax_km"] == pytest.approx(0.004, rel=1e-4)


# ---------------------------------------------------------------------------
# Phase 1: Real extraction outputs
# ---------------------------------------------------------------------------


class TestRealExtractionOutputs:
    @pytest.fixture(scope="class")
    def normalized(self) -> list[dict]:
        return _load_normalized()

    @pytest.fixture(scope="class")
    def sim_library(self) -> list[dict]:
        return _load_simulation_library()

    def test_record_count(self, normalized: list[dict]) -> None:
        assert len(normalized) == 85, f"Expected 85 records, got {len(normalized)}"

    def test_manufacturers_present(self, normalized: list[dict]) -> None:
        mfrs = {r["manufacturer"] for r in normalized}
        assert "Hino" in mfrs
        assert "Isuzu" in mfrs
        assert "MitsubishiFuso" in mfrs

    def test_categories_normalized(self, normalized: list[dict]) -> None:
        cats = {r["bus_category"] for r in normalized}
        assert cats.issubset({"route_bus", "coach_bus", "unknown"})

    def test_fuel_economy_positive(self, normalized: list[dict]) -> None:
        for r in normalized:
            fe = r.get("fuel_economy_km_per_L")
            if fe is not None:
                assert fe > 0, f"Non-positive fuel_economy in {r['model_code']}"

    def test_consistency_ok_all(self, normalized: list[dict]) -> None:
        flagged = [r for r in normalized if r.get("consistency_ok") is False]
        assert len(flagged) == 0, (
            f"Consistency failures: {[r['model_code'] for r in flagged]}"
        )

    def test_no_manual_review_flags(self, normalized: list[dict]) -> None:
        flagged = [r for r in normalized if r.get("needs_manual_review")]
        assert len(flagged) == 0

    def test_sim_library_size(self, sim_library: list[dict]) -> None:
        # 3 manufacturers * 2 categories * 3 modes = 18
        assert len(sim_library) == 18

    def test_sim_library_vehicle_types(self, sim_library: list[dict]) -> None:
        for entry in sim_library:
            assert entry["vehicle_type"] == "engine_bus"

    def test_sim_library_selection_modes(self, sim_library: list[dict]) -> None:
        modes = {e["selection_mode"] for e in sim_library}
        assert modes == {"representative", "conservative", "best_efficiency"}

    def test_sim_library_has_required_fields(self, sim_library: list[dict]) -> None:
        required = [
            "vehicle_id",
            "vehicle_type",
            "manufacturer",
            "model_code",
            "bus_category",
            "fuel_economy_km_per_L",
            "diesel_consumption_L_per_km",
            "co2_g_per_km",
            "source",
        ]
        for entry in sim_library:
            for f in required:
                assert f in entry, (
                    f"Missing field {f!r} in library entry {entry['vehicle_id']}"
                )


# ---------------------------------------------------------------------------
# Phase 2: select_vehicles() with synthetic data
# ---------------------------------------------------------------------------


class TestSelectVehicles:
    def test_representative_hino_route_bus(self) -> None:
        result = select_vehicles(
            _SYNTHETIC_RECORDS,
            mode="representative",
            manufacturer="Hino",
            bus_category="route_bus",
        )
        assert len(result) == 1
        # Two Hino route_bus records: fe=5.38 and fe=4.36; median=4.87 → closest is 5.38
        assert result[0]["model_code"] == "HINO-R01"

    def test_conservative_route_bus(self) -> None:
        result = select_vehicles(
            _SYNTHETIC_RECORDS, mode="conservative", bus_category="route_bus"
        )
        assert len(result) == 1
        # Lowest fe = 4.16 (MitsubishiFuso FUSO-R01)
        assert result[0]["model_code"] == "FUSO-R01"

    def test_best_efficiency_coach(self) -> None:
        result = select_vehicles(
            _SYNTHETIC_RECORDS, mode="best_efficiency", bus_category="coach_bus"
        )
        assert len(result) == 1
        assert result[0]["fuel_economy_km_per_L"] == 9.59

    def test_exact_match_by_model_code(self) -> None:
        result = select_vehicles(_SYNTHETIC_RECORDS, model_code="HINO-R02")
        assert len(result) == 1
        assert result[0]["model_code"] == "HINO-R02"

    def test_exact_match_capacity_range(self) -> None:
        result = select_vehicles(
            _SYNTHETIC_RECORDS,
            mode="exact_match",
            capacity_min=70,
            capacity_max=80,
        )
        # Records with capacity 70-80: HINO-R01 (79), FUSO-R01 (79)
        assert all(70 <= r["passenger_capacity"] <= 80 for r in result)

    def test_top_n_returns_multiple(self) -> None:
        result = select_vehicles(
            _SYNTHETIC_RECORDS,
            mode="representative",
            bus_category="route_bus",
            top_n=3,
        )
        assert len(result) == 3

    def test_empty_result_no_match(self) -> None:
        result = select_vehicles(_SYNTHETIC_RECORDS, manufacturer="Toyota")
        assert result == []

    def test_gvw_filter(self) -> None:
        result = select_vehicles(
            _SYNTHETIC_RECORDS,
            gvw_min=14000,
            gvw_max=15000,
        )
        assert all(14000 <= r["gross_vehicle_weight_kg"] <= 15000 for r in result)

    def test_power_filter(self) -> None:
        result = select_vehicles(
            _SYNTHETIC_RECORDS,
            power_min=200.0,
            mode="best_efficiency",
        )
        assert all(r["max_power_kW"] >= 200.0 for r in result)

    def test_isuzu_any_mode(self) -> None:
        result = select_vehicles(
            _SYNTHETIC_RECORDS, manufacturer="isuzu", mode="representative"
        )
        assert len(result) == 1
        assert result[0]["manufacturer"] == "Isuzu"
