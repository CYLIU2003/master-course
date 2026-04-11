from __future__ import annotations

import json
import math
from typing import Any

from bff.store.job_store import Job, job_to_dict


def _contains_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_contains_non_finite(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_non_finite(v) for v in value)
    return False


def test_job_to_dict_replaces_non_finite_metadata_values() -> None:
    job = Job(
        job_id="job-1",
        status="completed",
        progress=100,
        metadata={
            "objective_value": float("inf"),
            "nested": {"mip_gap": float("nan"), "ok": 0.0},
            "values": [1.0, float("-inf")],
        },
    )

    payload = job_to_dict(job)

    assert payload["metadata"]["objective_value"] is None
    assert payload["metadata"]["nested"]["mip_gap"] is None
    assert payload["metadata"]["values"][1] is None
    assert _contains_non_finite(payload) is False

    # FastAPI responses use strict JSON encoding; this must not raise.
    json.dumps(payload, allow_nan=False)
