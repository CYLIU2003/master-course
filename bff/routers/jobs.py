"""
bff/routers/jobs.py

Single endpoint: GET /jobs/{job_id}
Polls the in-memory job store for background task status.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from bff.store import job_store
from bff.desktop_models import JobReply

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobReply)
def get_job(job_id: str):
    try:
        job = job_store.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job_store.job_to_dict(job)
