from datetime import date, timedelta

from tools.research.weekly_campaign import WEEKS


def test_default_experiment_keeps_one_preselected_week_in_all_twelve_months():
    assert len(WEEKS) == len(set(WEEKS)) == 12
    assert [date.fromisoformat(w).month for w in WEEKS] == list(range(1, 13))
    assert WEEKS == (
        "2025-01-06", "2025-02-03", "2025-03-03", "2025-04-07",
        "2025-05-12", "2025-06-02", "2025-07-07", "2025-08-04",
        "2025-09-01", "2025-10-06", "2025-11-10", "2025-12-01",
    )
    for week in WEEKS:
        days = [date.fromisoformat(week) + timedelta(days=i) for i in range(7)]
        assert sum(d.weekday() < 5 for d in days) == 5
        assert len({d.month for d in days}) == 1
