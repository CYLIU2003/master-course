from __future__ import annotations

import re
from typing import Any, Dict

from fastapi import HTTPException
from pydantic import ValidationError

from bff.errors import AppErrorCode, make_error
from bff.routers.jobs import get_job
from bff.routers.optimization import (
    ReoptimizeBody,
    RunOptimizationBody,
    reoptimize,
    run_optimization,
)
from bff.routers.simulation import (
    PrepareSimulationBody,
    RunPreparedSimulationBody,
    prepare_simulation,
    run_prepared_simulation,
)
from bff.services import app_cache

_PREPARE_RE = re.compile(r"^/scenarios/(?P<scenario_id>[^/]+)/simulation/prepare$")
_RUN_PREPARED_SIM_RE = re.compile(r"^/scenarios/(?P<scenario_id>[^/]+)/simulation/run$")
_RUN_OPT_RE = re.compile(r"^/scenarios/(?P<scenario_id>[^/]+)/run-optimization$")
_REOPT_RE = re.compile(r"^/scenarios/(?P<scenario_id>[^/]+)/reoptimize$")
_JOB_RE = re.compile(r"^/jobs/(?P<job_id>[^/]+)$")


def is_direct_supported(method: str, path: str) -> bool:
    m = method.upper()
    return bool(
        (m == "POST" and (_PREPARE_RE.match(path) or _RUN_PREPARED_SIM_RE.match(path) or _RUN_OPT_RE.match(path) or _REOPT_RE.match(path)))
        or (m == "GET" and _JOB_RE.match(path))
    )


def _require_built_app_state() -> Dict[str, Any]:
    app_state = app_cache.get_app_state()
    if bool(app_state.get("built_ready")):
        return app_state
    raise RuntimeError(
        str(
            make_error(
                AppErrorCode.BUILT_DATASET_REQUIRED,
                "Built dataset is not available for direct runtime.",
                missing_artifacts=list(app_state.get("missing_artifacts") or []),
                integrity_error=app_state.get("integrity_error"),
            )
        )
    )


def call_direct(method: str, path: str, body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    method_upper = method.upper()
    payload = body or {}

    try:
        m = _PREPARE_RE.match(path)
        if method_upper == "POST" and m:
            scenario_id = m.group("scenario_id")
            return prepare_simulation(
                scenario_id,
                PrepareSimulationBody.model_validate(payload),
                _app_state=_require_built_app_state(),
            )

        m = _RUN_PREPARED_SIM_RE.match(path)
        if method_upper == "POST" and m:
            scenario_id = m.group("scenario_id")
            return run_prepared_simulation(
                scenario_id,
                RunPreparedSimulationBody.model_validate(payload),
                _app_state=_require_built_app_state(),
            )

        m = _RUN_OPT_RE.match(path)
        if method_upper == "POST" and m:
            scenario_id = m.group("scenario_id")
            parsed = (
                RunOptimizationBody.model_validate(payload)
                if payload
                else None
            )
            return run_optimization(
                scenario_id,
                parsed,
                _app_state=_require_built_app_state(),
            )

        m = _REOPT_RE.match(path)
        if method_upper == "POST" and m:
            scenario_id = m.group("scenario_id")
            return reoptimize(
                scenario_id,
                ReoptimizeBody.model_validate(payload),
                _app_state=_require_built_app_state(),
            )

        m = _JOB_RE.match(path)
        if method_upper == "GET" and m:
            return get_job(m.group("job_id"))

        raise RuntimeError(f"Direct runtime not supported for {method_upper} {path}")
    except ValidationError as exc:
        raise RuntimeError(f"Validation failed for direct runtime: {exc}") from exc
    except HTTPException as exc:
        raise RuntimeError(f"HTTP {exc.status_code}: {exc.detail}") from exc
