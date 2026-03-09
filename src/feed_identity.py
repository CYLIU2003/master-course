from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


TOKYU_ODPT_GTFS_FEED_ID = "tokyu_odpt_gtfs"
TOEI_GTFS_FEED_ID = "toei_gtfs"

_KNOWN_FEED_IDS = {
    "TokyuBus-GTFS": TOKYU_ODPT_GTFS_FEED_ID,
    "ToeiBus-GTFS": TOEI_GTFS_FEED_ID,
}

_KNOWN_OPERATORS = {
    TOKYU_ODPT_GTFS_FEED_ID: "TokyuBus",
    TOEI_GTFS_FEED_ID: "ToeiBus",
}

_KNOWN_SOURCE_TYPES = {
    TOKYU_ODPT_GTFS_FEED_ID: "odpt_json",
    TOEI_GTFS_FEED_ID: "gtfs_static",
}


def build_dataset_id(feed_id: str, snapshot_id: Optional[str]) -> str:
    if snapshot_id:
        return f"{feed_id}:{snapshot_id}"
    return feed_id


def build_scoped_id(feed_id: str, raw_id: Any) -> str:
    value = str(raw_id or "").strip()
    if not value:
        return ""
    prefix = f"{feed_id}:"
    if value.startswith(prefix):
        return value
    return f"{prefix}{value}"


def infer_feed_id(feed_path: str | Path) -> Optional[str]:
    path = Path(feed_path)
    for part in reversed(path.parts):
        feed_id = _KNOWN_FEED_IDS.get(part)
        if feed_id:
            return feed_id
    return None


def infer_operator(feed_id: str) -> str:
    return _KNOWN_OPERATORS.get(feed_id, "")


def infer_source_type(feed_id: str) -> str:
    return _KNOWN_SOURCE_TYPES.get(feed_id, "gtfs_static")


def build_feed_metadata(
    *,
    feed_id: str,
    snapshot_id: Optional[str],
    generated_at: Optional[str],
    source_type: Optional[str] = None,
    operator: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "feed_id": feed_id,
        "snapshot_id": snapshot_id,
        "dataset_id": build_dataset_id(feed_id, snapshot_id),
        "source_type": source_type or infer_source_type(feed_id),
        "operator": operator or infer_operator(feed_id),
        "generated_at": generated_at,
    }
    if extra:
        payload.update(extra)
    return payload


def load_feed_metadata(feed_root: str | Path) -> Dict[str, Any]:
    root = Path(feed_root)
    metadata_path = root / "feed_metadata.json"
    payload: Dict[str, Any] = {}
    if metadata_path.exists():
        with metadata_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            payload = dict(raw)

    feed_id = str(payload.get("feed_id") or infer_feed_id(root) or "")
    snapshot_id = payload.get("snapshot_id")
    normalized = build_feed_metadata(
        feed_id=feed_id,
        snapshot_id=str(snapshot_id) if snapshot_id else None,
        generated_at=str(payload.get("generated_at") or ""),
        source_type=str(payload.get("source_type") or "") or None,
        operator=str(payload.get("operator") or "") or None,
        extra={k: v for k, v in payload.items() if k not in {
            "feed_id",
            "snapshot_id",
            "dataset_id",
            "source_type",
            "operator",
            "generated_at",
        }},
    )
    if not normalized.get("generated_at"):
        normalized["generated_at"] = None
    return normalized
