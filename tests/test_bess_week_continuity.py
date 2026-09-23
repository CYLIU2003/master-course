from __future__ import annotations

from tools.research.check_bess_week_continuity import assess


def _week(start: str, initial: float, terminal: float) -> dict:
    return {
        "week": start,
        "bess_terminal": {
            "initial_soc_kwh": initial,
            "terminal_soc_kwh": terminal,
        },
    }


def test_contiguous_weeks_require_state_transfer() -> None:
    first = _week("2025-01-06", 3000, 1200)
    carried = _week("2025-01-13", 1200, 1400)
    reset = _week("2025-01-13", 3000, 1400)

    assert assess([carried, first])["status"] == "BOUNDARIES_CONSISTENT"
    assert assess([first, reset])["status"] == "CONTINUITY_NOT_ESTABLISHED"


def test_separated_representative_weeks_cannot_prove_continuity() -> None:
    verdict = assess([
        _week("2025-01-06", 3000, 1200),
        _week("2025-02-03", 3000, 1500),
    ])
    assert verdict["adjacent_pair_count"] == 0
    assert verdict["status"] == "CONTINUITY_NOT_ESTABLISHED"
