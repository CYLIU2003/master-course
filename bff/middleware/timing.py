from __future__ import annotations

import logging
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


log = logging.getLogger("perf")
ENABLED = os.environ.get("LOG_PERF", "0") == "1"


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not ENABLED:
            return await call_next(request)
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        size_bytes = int(response.headers.get("content-length", 0))
        log.info(
            "PERF %s %s %s %.1fms %sB",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            size_bytes,
        )
        return response
