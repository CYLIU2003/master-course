from __future__ import annotations

from typing import Any, Dict

from fastapi import Depends, HTTPException

from bff.errors import AppErrorCode, make_error
from bff.services import app_cache


def get_app_state() -> Dict[str, Any]:
    return app_cache.get_app_state()


async def require_built(app_state: Dict[str, Any] = Depends(get_app_state)) -> Dict[str, Any]:
    if bool(app_state.get("built_ready")):
        return app_state
    raise HTTPException(
        status_code=503,
        detail=make_error(
            AppErrorCode.BUILT_DATASET_REQUIRED,
            "Built dataset is not available. Run data-prep to generate built datasets first.",
            missing_artifacts=list(app_state.get("missing_artifacts") or []),
            integrity_error=app_state.get("integrity_error"),
        ),
    )


async def require_seed(app_state: Dict[str, Any] = Depends(get_app_state)) -> Dict[str, Any]:
    if bool(app_state.get("seed_ready")):
        return app_state
    raise HTTPException(
        status_code=503,
        detail=make_error(
            AppErrorCode.SEED_DATASET_REQUIRED,
            "Seed dataset failed to load. Check data/seed/tokyu/.",
        ),
    )
