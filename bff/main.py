"""
bff/main.py

FastAPI BFF (Backend For Frontend) for the EV bus scheduling React app.

All routes are mounted under /api so the React frontend's BASE_URL = "/api"
resolves correctly when using the Vite dev proxy.

Run:
    uvicorn bff.main:app --reload --port 8000

Or use the helper script:
    python -m bff.main
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bff.routers import (
    catalog,
    graph,
    jobs,
    master_data,
    optimization,
    scenarios,
    simulation,
    timetable,
)

app = FastAPI(
    title="EV Bus Scheduling BFF",
    description="Backend For Frontend — bridges the React UI to the Python dispatch pipeline.",
    version="0.1.0",
)

# ── CORS ───────────────────────────────────────────────────────
# Allow the Vite dev server (localhost:5173) to call the BFF.
# In production (same origin), CORS is not needed.

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────

PREFIX = "/api"

app.include_router(scenarios.router, prefix=PREFIX)
app.include_router(timetable.router, prefix=PREFIX)
app.include_router(master_data.router, prefix=PREFIX)
app.include_router(catalog.router, prefix=PREFIX)
app.include_router(graph.router, prefix=PREFIX)
app.include_router(simulation.router, prefix=PREFIX)
app.include_router(optimization.router, prefix=PREFIX)
app.include_router(jobs.router, prefix=PREFIX)


# ── Health check ───────────────────────────────────────────────


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ── Dev runner ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("bff.main:app", host="0.0.0.0", port=8000, reload=True)
