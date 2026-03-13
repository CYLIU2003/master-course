from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.gtfs_runtime import (
    get_latest_tokyubus_snapshot_id,
    list_tokyubus_snapshots,
    load_tokyubus_snapshot_bundle,
)


def list_runtime_snapshots() -> List[Dict[str, Any]]:
    return list_tokyubus_snapshots()


def get_latest_runtime_snapshot_id() -> Optional[str]:
    return get_latest_tokyubus_snapshot_id()


def load_runtime_snapshot(snapshot_id: Optional[str] = None) -> Dict[str, Any]:
    return load_tokyubus_snapshot_bundle(snapshot_id=snapshot_id)
