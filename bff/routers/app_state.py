from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from bff.errors import AppErrorCode, make_error
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
    }


@router.get("/app-state")
def get_app_state(
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
        "dataset_id": item.get("datasetId") or dataset_id,
        "dataset_version": item.get("datasetVersion"),
        "seed_ready": bool(item.get("seedReady")),
        "built_ready": bool(item.get("builtReady")),
        "missing_artifacts": list(item.get("missingArtifacts") or []),
        "integrity_error": item.get("integrityError"),
    }
