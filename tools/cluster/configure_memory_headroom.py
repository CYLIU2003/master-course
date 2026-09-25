"""Raise per-PC admission reserves without changing jobs or solver settings.

Run against each controller's administrator-owned config, then restart only
that controller to load it. Accepted remote attempts continue independently.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.services.cluster.contracts import ClusterConfig, canonical


def raise_reserves(config: ClusterConfig) -> list[dict]:
    changes = []
    for worker in config.workers:
        # Add headroom beyond memory already occupied by Windows and other apps.
        floor = 6.0 if worker.transport == "local" else 4.0
        before = worker.reserved_system_ram_gb
        worker.reserved_system_ram_gb = max(before, floor)
        changes.append({"worker_id": worker.id, "before_gb": before,
                        "reserved_system_ram_gb": worker.reserved_system_ram_gb})
    return changes


def configure(path: Path, *, apply: bool = False) -> dict:
    original = path.read_bytes()
    config = ClusterConfig.model_validate_json(original)
    changes = raise_reserves(config)
    report = {"config": str(path.resolve()), "applied": False, "workers": changes}
    if apply:
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
        backup = path.with_name(path.name + ".backup-" + suffix)
        backup.write_bytes(original)
        temporary = path.with_name(path.name + ".tmp-" + suffix)
        temporary.write_bytes(canonical(config.model_dump()))
        if path.read_bytes() != original:
            raise RuntimeError("Configuration changed concurrently; refusing to overwrite")
        temporary.replace(path)
        report.update(applied=True, backup=str(backup.resolve()))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--apply", action="store_true", help="Save with an original-byte backup")
    args = parser.parse_args()
    print(json.dumps(configure(args.config, apply=args.apply), ensure_ascii=False, indent=2))
