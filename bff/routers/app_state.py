from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from bff.errors import AppErrorCode, make_error
from bff.services import app_cache
from bff.services import master_defaults
from bff.services import research_catalog

router = APIRouter(tags=["app-state"])


@router.get("/app/datasets")
def list_research_datasets() -> dict:
    items = research_catalog.list_datasets()
    return {
        "items": items,
        "total": len(items),
        "defaultDatasetId": research_catalog.default_dataset_id(),
    }


@router.get("/app/data-status")
def get_app_data_status(
    dataset_id: str = Query(
        default=research_catalog.default_dataset_id(),
        alias="datasetId",
    ),
) -> dict:
    try:
        item = research_catalog.get_dataset(dataset_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=make_error(
                AppErrorCode.MISSING_ARTIFACT,
                f"Dataset '{dataset_id}' not found",
                datasetId=dataset_id,
            ),
        )
    return {
        "item": item,
        "seed_ready": bool(item.get("seedReady")),
        "built_ready": bool(item.get("builtReady")),
        "missing_artifacts": list(item.get("missingArtifacts") or []),
        "integrity_error": item.get("integrityError"),
        "producer_version": item.get("producerVersion"),
        "schema_version": item.get("schemaVersion"),
        "runtime_version": item.get("runtimeVersion"),
        "contract_error_code": item.get("contractErrorCode"),
    }


@router.get("/app-state")
def get_app_state(
    dataset_id: str = Query(
        default=research_catalog.default_dataset_id(),
        alias="datasetId",
    ),
) -> dict:
    try:
        item = app_cache.get_app_state(dataset_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=make_error(
                AppErrorCode.MISSING_ARTIFACT,
                f"Dataset '{dataset_id}' not found",
                datasetId=dataset_id,
            ),
        )
    return {
        "dataset_id": item.get("dataset_id") or dataset_id,
        "dataset_version": item.get("dataset_version"),
        "producer_version": item.get("producer_version"),
        "schema_version": item.get("schema_version"),
        "runtime_version": item.get("runtime_version"),
        "seed_ready": bool(item.get("seed_ready")),
        "built_ready": bool(item.get("built_ready")),
        "missing_artifacts": list(item.get("missing_artifacts") or []),
        "integrity_error": item.get("integrity_error"),
        "contract_error_code": item.get("contract_error_code"),
    }


@router.get("/app/master-data")
def get_app_master_data(
    dataset_id: str = Query(
        default=master_defaults.default_preload_dataset_id(),
        alias="datasetId",
    ),
) -> dict:
    item = app_cache.get_cached(
        f"app:master-data:{dataset_id}",
        lambda: master_defaults.get_preloaded_master_data(dataset_id),
    )
    return dict(item)
