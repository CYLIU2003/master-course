"""The scenario picker groups labels without altering solver inputs."""

import pytest

from bff.store.desktop_store import scenario_route_group


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("渋24 ODPT実便 2025-05-12", "shibu24"),
        ("渋21-24 7日入力候補", "shibu21_24"),
        ("渋21-渋22-渋23 7日入力候補", "shibu21_23"),
        ("Shibu21_test training_only_forecast_proxy", "shibu21_23"),
        ("771d115b-75b0-49f7-a7f0-25f259a2cd21", "other"),
        ("Route 24 diagnostic", "other"),
    ],
)
def test_saved_name_display_group(name: str, expected: str) -> None:
    assert scenario_route_group(name) == expected
