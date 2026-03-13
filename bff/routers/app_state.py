from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

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
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    return {"item": item}
