from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator


log = logging.getLogger("metrics")


@contextmanager
def timed(label: str) -> Iterator[None]:
    started = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    log.debug("TIMED %s: %.1fms", label, elapsed_ms)
