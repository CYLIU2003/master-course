"""Explicit timetable import/export with complete rows and no source invention."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from bff.services.desktop_configuration import configuration
from bff.store import desktop_store, scenario_store
from bff.store.output_paths import outputs_root

_REQUIRED = ("trip_id", "route_id", "service_id", "departure", "arrival", "operator_id", "distance_km")


def input_revision(scenario_id: str) -> str:
    _, refs = scenario_store.get_desktop_context(scenario_id)
    snapshot = [configuration(scenario_id)["revision"]]
    for key, value in sorted(refs.items()):
        path = Path(value)
        if path.is_file():
            stat = path.stat()
            snapshot.append((key, stat.st_mtime_ns, stat.st_size))
    return hashlib.sha256(json.dumps(snapshot).encode()).hexdigest()


def parse_timetable_csv(content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("CSVには重複のない列名が必要です。")
    missing = set(_REQUIRED) - set(reader.fieldnames)
    if missing:
        raise ValueError("必要な列がありません: " + ", ".join(sorted(missing)))
    rows, identities = [], set()
    for number, raw in enumerate(reader, start=2):
        if None in raw or any(value is None for value in raw.values()):
            raise ValueError(f"CSV {number}行目: 列数が一致しません。")
        row = {}
        for key, value in raw.items():
            # Our export encodes every cell as JSON; ordinary CSV strings are
            # also accepted. IDs are never generated or normalized.
            if value == "" and key not in _REQUIRED:
                continue
            try:
                preserve_text = key.endswith("_id") or key in {"departure", "arrival", "service_date"}
                row[key] = value if preserve_text and not value.startswith('"') else json.loads(value)
            except json.JSONDecodeError:
                row[key] = value
        if any(not str(row.get(key) or "").strip() for key in _REQUIRED):
            raise ValueError(f"CSV {number}行目: 必須項目が空です。")
        if str(row["operator_id"]).strip().upper() == "UNKNOWN":
            raise ValueError(f"CSV {number}行目: operator_id=UNKNOWN は取り込めません。")
        times = []
        for key in ("departure", "arrival"):
            match = re.fullmatch(r"(\d+):([0-5]\d)(?::([0-5]\d))?", str(row[key]))
            if not match:
                raise ValueError(f"CSV {number}行目: {key} はHH:MMまたはHH:MM:SSで指定してください。")
            hours, minutes, seconds = match.groups()
            times.append(int(hours) * 3600 + int(minutes) * 60 + int(seconds or 0))
        if times[1] < times[0]:
            raise ValueError(f"CSV {number}行目: 到着が出発より前です。翌日の時刻は24時以降で指定してください。")
        try:
            distance = float(row["distance_km"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"CSV {number}行目: distance_km は数値が必要です。") from exc
        if not math.isfinite(distance) or distance <= 0:
            raise ValueError(f"CSV {number}行目: distance_km は有限の正数が必要です。")
        identity = (str(row["trip_id"]), str(row.get("service_date", "")), str(row["service_id"]))
        if identity in identities:
            raise ValueError(f"CSV {number}行目: 同じ運行日の便IDが重複しています。")
        identities.add(identity)
        row["distance_km"] = distance
        if isinstance(row.get("allowed_vehicle_types"), str):
            row["allowed_vehicle_types"] = row["allowed_vehicle_types"].split(";")
        rows.append(row)
    if not rows:
        raise ValueError("空の時刻表では置き換えできません。")
    return rows


def import_timetable(scenario_id: str, content: str, apply: bool, revision: str) -> dict:
    with scenario_store._scenario_lock(scenario_id):
        return _import_timetable_locked(scenario_id, content, apply, revision)


def _import_timetable_locked(scenario_id: str, content: str, apply: bool, revision: str) -> dict:
    current = input_revision(scenario_id)
    rows = parse_timetable_csv(content)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    stamp = hashlib.sha256((current + digest).encode()).hexdigest()
    if apply:
        if revision != stamp:
            raise ValueError("入力ファイルまたは保存されたシナリオが変わりました。もう一度検査してください。")
        backup = export_timetable(scenario_id)
        if input_revision(scenario_id) != current:
            raise ValueError("バックアップ中に入力が変わりました。もう一度検査してください。")
        scenario_store.set_field(scenario_id, "timetable_rows", rows, invalidate_dispatch=True)
        return {"valid": True, "applied": True, "rows": len(rows), "source_sha256": digest, "previous_timetable": backup}
    return {"valid": True, "applied": False, "rows": len(rows), "source_sha256": digest, "revision": stamp, "preview": rows[:5]}


def export_timetable(scenario_id: str) -> dict:
    stamp = input_revision(scenario_id)
    _, refs = scenario_store.get_desktop_context(scenario_id)
    db = Path(refs["artifactStore"])
    output = outputs_root() / "desktop_exports" / f"timetable_{uuid4().hex}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    # SQLite export reads every persisted timetable row, including compatibility
    # aliases hidden by the UI. A read transaction keeps both passes consistent.
    if db.exists():
        with closing(desktop_store._read_connection(db)) as conn:
            conn.execute("BEGIN")
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='timetable_rows'").fetchone()
            if exists and conn.execute("SELECT 1 FROM timetable_rows LIMIT 1").fetchone():
                def source():
                    for row in conn.execute("SELECT payload_json FROM timetable_rows ORDER BY row_index"):
                        yield json.loads(row[0])
                count = _write_csv(output, source)
                return {"path": str(output), "rows": count, "format": "CSV with JSON-encoded cells", "source_revision": stamp}
    def source():
        offset = 0
        while True:
            items = scenario_store.page_timetable_rows(scenario_id, offset=offset, limit=500)
            if not items:
                return
            yield from items
            offset += len(items)
    count = _write_csv(output, source)
    if input_revision(scenario_id) != stamp:
        raise ValueError(f"書出し中に入力が変わりました。未確定の出力: {output}")
    return {"path": str(output), "rows": count, "format": "CSV with JSON-encoded cells", "source_revision": stamp, "scope": "legacy visible timetable rows"}


def _write_csv(path: Path, source) -> int:
    fields = list(dict.fromkeys(key for row in source() for key in row))
    count = 0
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in source():
            writer.writerow({key: json.dumps(value, ensure_ascii=False, allow_nan=False) for key, value in row.items()})
            count += 1
    return count
