import math

import pytest

from tools.research.monthly_power_evidence import close, index_proofs, metrics


def test_quarter_hour_power_and_full_period_mean_are_distinct():
    result = metrics([0., 75., 25., 0.], 200.)
    assert result['hours'] == 1.
    assert result['grid_import_kwh'] == 100.
    assert result['mean_grid_kw'] == 100.
    assert result['peak_grid_kw'] == 300.
    assert result['peak_slot'] == 1
    assert result['over_contract_kwh'] == 25.
    assert result['over_contract_hours'] == .25


def test_counting_tolerance_does_not_erase_excess_energy():
    result = metrics([50.000025, 50.], 200.)
    assert result['over_contract_hours'] == 0.
    assert result['over_contract_kwh'] == pytest.approx(.000025)


@pytest.mark.parametrize('energy,limit', [([], 200.), ([math.nan], 200.),
                                        ([-1.], 200.), ([1.], -1.), ([1.], math.inf)])
def test_invalid_series_and_threshold_are_rejected(energy, limit):
    with pytest.raises(ValueError):
        metrics(energy, limit)


def test_nonfinite_or_mismatched_accounting_is_rejected():
    for actual, expected in [(math.nan, 0.), (0., math.inf), (1., 2.)]:
        with pytest.raises(ValueError):
            close(actual, expected, 'accounting')


def test_duplicate_week_evidence_is_rejected_even_in_different_directories():
    with pytest.raises(ValueError, match='Duplicate evidence'):
        index_proofs([{'case': 'first/2025-03-03'}, {'case': 'second/2025-03-03'}])
