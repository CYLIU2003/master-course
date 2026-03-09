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

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Load environment variables from .env files (before any other import that
# might read os.environ).  We check multiple candidate locations.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]

_ENV_CANDIDATES = [
    _REPO_ROOT / ".env",            # project-root .env
    _REPO_ROOT / "bff" / ".env",    # bff-specific .env
    _REPO_ROOT / "backend" / ".env",  # legacy backend .env
]


def _load_dotenv() -> None:
    """Minimal .env loader — no external dependency required."""
    for env_path in _ENV_CANDIDATES:
        if not env_path.exists():
            continue
        with env_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value


_load_dotenv()

# Map legacy ODPT_TOKEN → ODPT_CONSUMER_KEY if needed
if "ODPT_CONSUMER_KEY" not in os.environ and "ODPT_TOKEN" in os.environ:
    os.environ["ODPT_CONSUMER_KEY"] = os.environ["ODPT_TOKEN"]

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from bff.routers import (
    catalog,
    graph,
    jobs,
    master_data,
    optimization,
    public_data,
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

default_allow_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]
allow_origins_env = os.getenv("BFF_CORS_ALLOW_ORIGINS", "")
allow_origins = [
    origin.strip()
    for origin in allow_origins_env.split(",")
    if origin.strip()
] or default_allow_origins
allow_origin_regex = os.getenv(
    "BFF_CORS_ALLOW_ORIGIN_REGEX",
    r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────

PREFIX = "/api"

app.include_router(scenarios.router, prefix=PREFIX)
app.include_router(timetable.router, prefix=PREFIX)
app.include_router(master_data.router, prefix=PREFIX)
app.include_router(public_data.router, prefix=PREFIX)
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
