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

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from time import perf_counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Load environment variables from .env files (before any other import that
# might read os.environ).  We check multiple candidate locations.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]

_ENV_CANDIDATES = [
    _REPO_ROOT / ".env",            # project-root .env
    _REPO_ROOT / "bff" / ".env",    # bff-specific .env
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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import os

from bff.routers import (
    app_state,
    graph,
    jobs,
    master_data,
    optimization,
    scenarios,
    simulation,
    timetable,
)
from bff.services import app_cache

_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    warmup_task = asyncio.create_task(asyncio.to_thread(app_cache.warm_startup_cache))
    app.state.cache_warmup_task = warmup_task
    try:
        yield
    finally:
        if not warmup_task.done():
            warmup_task.cancel()
        simulation.shutdown_simulation_executor()
        optimization.shutdown_optimization_executor()

app = FastAPI(
    title="EV Bus Scheduling BFF",
    description="Tokyu Bus research BFF consuming prebuilt seed and dataset files.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_request_metrics(request: Request, call_next):
    started = perf_counter()
    response = await call_next(request)
    duration_ms = (perf_counter() - started) * 1000.0
    payload_size = response.headers.get("content-length", "unknown")
    _log.info(
        "%s %s -> %s in %.1fms (payload=%s)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        payload_size,
    )
    return response

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
app.include_router(app_state.router, prefix=PREFIX)
app.include_router(timetable.router, prefix=PREFIX)
app.include_router(master_data.router, prefix=PREFIX)
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
