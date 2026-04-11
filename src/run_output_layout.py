from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
import re


def _normalize_run_date(run_date: str | None, *, fallback: Optional[datetime] = None) -> str:
    text = str(run_date or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    return (fallback or datetime.now()).strftime("%Y-%m-%d")


def allocate_run_dir(
    output_root: str | Path,
    run_date: str | None = None,
    *,
    timestamp: Optional[datetime] = None,
) -> Path:
    """Create and return ``output/<date>/run_YYYYMMDD_HHMM[/_NN]``.

    The directory is created immediately so callers can persist artifacts
    without re-resolving collisions.
    """

    date_root = Path(output_root) / _normalize_run_date(run_date, fallback=timestamp)
    date_root.mkdir(parents=True, exist_ok=True)

    ts = timestamp or datetime.now()
    base_name = ts.strftime("run_%Y%m%d_%H%M")
    candidate = date_root / base_name
    suffix = 2
    while candidate.exists():
        candidate = date_root / f"{base_name}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate