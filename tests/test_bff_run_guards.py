import pytest
from fastapi import HTTPException

from bff.dependencies import require_built


@pytest.mark.anyio
async def test_require_built_rejects_seed_only_state():
    with pytest.raises(HTTPException) as exc:
        await require_built(
            {
                "seed_ready": True,
                "built_ready": False,
                "missing_artifacts": ["data/built/tokyu_core/trips.parquet"],
                "integrity_error": None,
            }
        )

    assert exc.value.status_code == 503
    detail = dict(exc.value.detail)
    assert detail["error"] == "BUILT_DATASET_REQUIRED"


@pytest.mark.anyio
async def test_require_built_allows_built_ready_state():
    app_state = {
        "seed_ready": True,
        "built_ready": True,
        "missing_artifacts": [],
        "integrity_error": None,
    }
    result = await require_built(app_state)
    assert result == app_state
