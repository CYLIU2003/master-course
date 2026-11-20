"""Sequence counterfactual: actual PV days are reordered, nothing else (2026-11-21)."""
import pytest

from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import permute_actual_pv_days


def _profiles(n):
    return [{"date": f"2025-01-{6 + i:02d}", "slot_minutes": 15, "capacity_factor_by_slot": [float(i)] * 96}
            for i in range(n)]


def test_order_moves_curves_keeps_dates_and_total():
    base = _profiles(8)
    out = permute_actual_pv_days(base, [6, 5, 4, 3, 2, 1, 0])
    assert [p["date"] for p in out] == [p["date"] for p in base]
    assert out[0]["capacity_factor_by_slot"][0] == 6.0 and out[0]["pv_source_date"] == "2025-01-12"
    assert out[7] is base[7]  # the next morning is not moved
    assert sum(sum(p["capacity_factor_by_slot"]) for p in out) == sum(sum(p["capacity_factor_by_slot"]) for p in base)


def test_none_keeps_measured_order():
    base = _profiles(8)
    assert permute_actual_pv_days(base, None) is base


@pytest.mark.parametrize("order", [[0, 0, 1, 2, 3, 4, 5], [0, 1, 2], list(range(9)), "0123456"])
def test_non_permutations_are_rejected(order):
    if order == [0, 1, 2]:
        assert len(permute_actual_pv_days(_profiles(8), order)) == 8  # a prefix permutation is allowed
        return
    with pytest.raises(ValueError):
        permute_actual_pv_days(_profiles(8), order)
