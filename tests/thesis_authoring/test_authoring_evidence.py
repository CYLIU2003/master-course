from __future__ import annotations

import pytest

from tools.thesis_authoring.build_authoring_evidence import (
    average_ranks,
    pearson_correlation,
    spearman_rank_correlation,
)


def test_average_ranks_uses_average_for_ties() -> None:
    assert average_ranks([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]


def test_correlations_are_exact_for_monotone_sequences() -> None:
    assert pearson_correlation([1, 2, 3], [3, 6, 9]) == pytest.approx(1.0)
    assert spearman_rank_correlation([30, 10, 20], [3, 1, 2]) == pytest.approx(1.0)


def test_correlation_rejects_constant_sequence() -> None:
    with pytest.raises(RuntimeError, match="constant sequence"):
        pearson_correlation([1, 1, 1], [1, 2, 3])
