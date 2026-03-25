from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def outputs_root() -> Path:
    value = str(os.environ.get("MC_OUTPUTS_DIR") or "").strip()
    if value:
        return Path(value)
    return project_root() / "output"


def scenarios_root() -> Path:
    value = str(os.environ.get("SCENARIO_STORE_PATH") or "").strip()
    if value:
        return Path(value)
    return outputs_root() / "scenarios"
