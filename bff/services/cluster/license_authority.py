"""One durable parent queue owns a WLS pool across controller ports/releases.

The owner does not expire on restart or disconnect. Moving it is deliberately
not automatic: unresolved attempts must remain with their original queue.
"""
from pathlib import Path
import json
import os

from .store import ControllerLock
from tools.cluster.atomic_file import replace_bytes


def authority_path() -> Path:
    return Path(os.environ.get("MC_GUROBI_AUTHORITY_FILE", Path.home() / ".master-course/gurobi-authority.json"))


def claim_authority(path: Path, queue: Path) -> None:
    with_lock = ControllerLock(path.parent / ".gurobi-authority-lock")
    try:
        expected = str(queue.resolve())
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema") != 1 or Path(data["queue"]).resolve() != queue.resolve():
                raise ValueError("GUROBI_AUTHORITY_OTHER_QUEUE: retain and reconcile the designated parent queue")
        else:
            replace_bytes(path, json.dumps({"schema": 1, "queue": expected}).encode())
    finally:
        with_lock.close()


def has_authority(path: Path, queue: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("schema") == 1 and Path(data["queue"]).resolve() == queue.resolve()
    except (OSError, ValueError, KeyError, TypeError):
        return False
