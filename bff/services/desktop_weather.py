"""Explicit local weather actions shared with the Tkinter preprocessing path."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from bff.store.output_paths import outputs_root, project_root
from src.preprocess.weather.weather_proxy_builder import (
    build_weather_proxy_forecast, load_weather_proxy_forecast_json,
    write_weather_proxy_forecast_json,
)
from src.preprocess.weather.solcast_pv_proxy import build_solcast_pv_proxy_forecast
from src.preprocess.weather.solcast_typical import (
    build_representative_curve_payload, load_solcast_daily_pv_profiles,
)
from src.preprocess.weather.solcast_typical.forecast import build_solcast_typical_proxy_forecast


def local_source(value: str) -> Path:
    path = Path(value)
    path = (project_root() / path).resolve() if not path.is_absolute() else path.resolve()
    allowed = [(project_root() / "data").resolve(), outputs_root().resolve()]
    if not any(path.is_relative_to(root) for root in allowed):
        raise ValueError("気象データはプロジェクトの data または output 内を指定してください。")
    if path.suffix.lower() not in {".csv", ".json"} or not path.is_file():
        raise ValueError("存在するCSVまたはJSONを指定してください。")
    if path.stat().st_size > 50_000_000:
        raise ValueError("この操作の入力上限は50 MBです。日別ファイルを指定してください。")
    return path


def import_source(filename: str, content: str) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".json"} or not content.strip():
        raise ValueError("UTF-8のCSVまたはJSONを選択してください。")
    if suffix == ".json":
        json.loads(content.lstrip("\ufeff"))
    output = outputs_root() / "desktop_weather" / "sources" / f"{uuid4().hex}{suffix}"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as stream:
        stream.write(content)
    return {"path": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "original_filename": Path(filename).name}


def weather_action(body) -> dict:
    path = local_source(body.source_path) if body.action != "representative" else None
    if body.action == "inspect":
        load_weather_proxy_forecast_json(path)
        return {"path": str(path), "payload": json.loads(path.read_text(encoding="utf-8"))}
    output = outputs_root() / "desktop_weather" / f"{body.action}_{uuid4().hex}.json"
    common = dict(service_date=body.service_date, station_id=body.station_id, station_name=body.station_name)
    if body.action == "historical":
        forecast = build_weather_proxy_forecast(**common, daily_weather_csv_path=str(path), random_seed=body.random_seed)
    elif body.action == "pv_proxy":
        forecast = build_solcast_pv_proxy_forecast(**common, pv_profile_json_path=path, forecast_issue_date=body.issue_date or None)
    elif body.action == "typical_proxy":
        forecast = build_solcast_typical_proxy_forecast(**common, representative_curve_json_path=path, weather_class=body.weather_class, forecast_issue_date=body.issue_date or None)
    elif body.action == "representative":
        profiles = load_solcast_daily_pv_profiles(profile_dir=project_root() / "data/derived/pv_profiles", glob_pattern=f"{re.sub(r'[^0-9A-Za-z_-]+', '_', body.depot_id)}_*_60min.json", depot_id=body.depot_id)
        payload = build_representative_curve_payload(profiles, station_id=body.station_id, station_name=body.station_name, depot_id=body.depot_id)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(output), "payload": payload, "kind": "representative_curve"}
    else:
        raise ValueError("Unsupported weather action")
    write_weather_proxy_forecast_json(output, forecast)
    return {"path": str(output), "payload": json.loads(output.read_text(encoding="utf-8")), "kind": "forecast_proxy", "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
