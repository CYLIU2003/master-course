from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def persist_json_outputs(output_dir: str, payloads: Dict[str, Dict[str, Any]]) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output_path / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def run_stamp() -> str:
    return datetime.now().strftime("run_%Y%m%d_%H%M")


def service_date_for_output(scenario: Dict[str, Any]) -> str:
    sim = dict(scenario.get("simulation_config") or {})
    primary = str(sim.get("service_date") or "").strip()
    if primary:
        return primary[:10]
    dates = [str(v).strip() for v in list(sim.get("service_dates") or []) if str(v).strip()]
    if dates:
        return dates[0][:10]
    return datetime.now().strftime("%Y-%m-%d")


def write_csv_rows(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
