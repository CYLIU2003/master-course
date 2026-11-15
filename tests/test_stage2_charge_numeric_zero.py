"""Stage 2 extraction: numerical charge residues vs real charging without a charger (2026-11-15)."""
import pytest

from src.optimization.milp.solver_adapter import (
    STAGE2_NUMERIC_ZERO_CHARGE_KW,
    _is_stage2_charge_integrality_noise as noise,
)

TOL = dict(max_charger_kw=60.0, feasibility_tol=1e-9, integrality_tol=1e-9)


@pytest.mark.parametrize(
    "charge_kw, charge_on",
    [
        (9.999999997489795e-05, 1.6666249995816323e-06),  # rc39 etb900 2025-07-07 step 170
        (0.00010000000010653534, 3.3333333368844986e-06),  # rc39 eti900 2025-07-07 step 53
        (0.0003157894797530054, 3.5087164417000602e-06),  # rc39 eti900 2025-01-06
    ],
)
def test_observed_rc39_residues_are_numerical_zero(charge_kw, charge_on):
    assert noise(charge_kw=charge_kw, charge_on=charge_on, assignment_values=[0.0, charge_on], **TOL)


def test_real_power_without_charger_still_rejected():
    assert not noise(charge_kw=STAGE2_NUMERIC_ZERO_CHARGE_KW * 2, charge_on=1e-6, assignment_values=[0.0], **TOL)
    assert not noise(charge_kw=5.0, charge_on=1e-6, assignment_values=[0.0], **TOL)


def test_selected_binary_is_never_noise():
    assert not noise(charge_kw=1e-4, charge_on=0.3, assignment_values=[0.0], **TOL)
    assert not noise(charge_kw=1e-4, charge_on=1e-6, assignment_values=[0.2], **TOL)


def test_loose_configured_tolerance_widens_band_consistently():
    # IntFeasTol 1e-3 with a 60 kW charger permits up to 0.06 kW under c <= P*on.
    assert noise(charge_kw=0.05, charge_on=1e-3, assignment_values=[1e-3], max_charger_kw=60.0,
                 feasibility_tol=1e-6, integrality_tol=1e-3)
