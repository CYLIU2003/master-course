from __future__ import annotations

from pathlib import Path


_HERE = Path(__file__).resolve().parents[1]


def get_producer_version() -> str:
    version_file = _HERE / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


def get_min_runtime_version() -> str:
    version_file = _HERE / "MIN_RUNTIME_VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return get_producer_version()
