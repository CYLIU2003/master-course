from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.feed_identity import (
    TOKYU_ODPT_GTFS_FEED_ID,
    build_dataset_id,
)

from .constants import GTFS_OUTPUT_DIR

_REQUIRED_FILES = (
    "agency.txt",
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
    "calendar.txt",
    "calendar_dates.txt",
)


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload if isinstance(payload, dict) else {}


def _csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _jsonl_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _row_count(path: Path) -> int:
    return len(_csv_rows(path))


def _shape_id_count(rows: Iterable[Dict[str, str]]) -> int:
    return len({str(row.get("shape_id") or "").strip() for row in rows if row.get("shape_id")})


def _time_to_seconds(value: str) -> Optional[int]:
    parts = str(value or "").strip().split(":")
    if len(parts) != 3:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2])
    except ValueError:
        return None
    return hour * 3600 + minute * 60 + second


def _validate_external_command(
    gtfs_dir: Path,
    validator_command: Optional[str],
) -> Dict[str, Any]:
    if not validator_command:
        return {"status": "skipped", "reason": "validator_command_not_provided"}

    with tempfile.TemporaryDirectory(prefix="tokyu-gtfs-validate-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        feed_zip = tmp_dir / "feed.zip"
        report_dir = tmp_dir / "validator-output"
        report_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(feed_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in gtfs_dir.iterdir():
                if file_path.is_file():
                    zf.write(file_path, arcname=file_path.name)
        command = validator_command.format(
            feed_zip=str(feed_zip),
            report_dir=str(report_dir),
        )
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "status": "passed" if completed.returncode == 0 else "failed",
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "report_dir": str(report_dir),
        }


def validate_gtfs_feed(
    canonical_dir: Path,
    *,
    gtfs_dir: Path = GTFS_OUTPUT_DIR,
    report_path: Optional[Path] = None,
    validator_command: Optional[str] = None,
) -> Dict[str, Any]:
    canonical_summary = _read_json(canonical_dir / "canonical_summary.json")
    gtfs_files = {name: gtfs_dir / name for name in _REQUIRED_FILES}

    file_checks = {
        name: {
            "exists": path.exists(),
            "non_empty": path.exists() and path.stat().st_size > 0,
            "rows": _row_count(path) if path.exists() else 0,
        }
        for name, path in gtfs_files.items()
    }

    counts = {
        "canonical": dict(canonical_summary.get("entity_counts") or {}),
        "gtfs": {
            "routes": file_checks["routes.txt"]["rows"],
            "stops": file_checks["stops.txt"]["rows"],
            "trips": file_checks["trips.txt"]["rows"],
            "stop_times": file_checks["stop_times.txt"]["rows"],
            "services": file_checks["calendar.txt"]["rows"],
            "calendar_dates": file_checks["calendar_dates.txt"]["rows"],
            "shapes": _shape_id_count(_csv_rows(gtfs_dir / "shapes.txt"))
            if (gtfs_dir / "shapes.txt").exists()
            else 0,
        },
    }
    public_trips = [
        row
        for row in _jsonl_rows(canonical_dir / "trips.jsonl")
        if row.get("is_public_trip", True)
    ]
    public_trip_ids = {str(trip.get("trip_id") or "") for trip in public_trips}
    counts["canonical"]["public_trips"] = len(public_trips)
    counts["canonical"]["public_stop_times"] = len(
        [
            row
            for row in _jsonl_rows(canonical_dir / "stop_times.jsonl")
            if str(row.get("trip_id") or "") in public_trip_ids
        ]
    )
    counts["canonical"]["shape_ids"] = len(
        {
            str(row.get("shape_id") or "")
            for row in public_trips
            if row.get("shape_id")
        }
    )

    count_alignment = {
        "routes": counts["canonical"].get("routes", 0) == counts["gtfs"]["routes"],
        "stops": counts["canonical"].get("stops", 0) == counts["gtfs"]["stops"],
        "trips": counts["canonical"].get("public_trips", 0) == counts["gtfs"]["trips"],
        "stop_times": counts["canonical"].get("public_stop_times", 0)
        == counts["gtfs"]["stop_times"],
        "services": counts["canonical"].get("services", 0) == counts["gtfs"]["services"],
        "shapes": counts["canonical"].get("shape_ids", 0) == counts["gtfs"]["shapes"],
    }

    routes_rows = _csv_rows(gtfs_dir / "routes.txt")
    trips_rows = _csv_rows(gtfs_dir / "trips.txt")
    stop_times_rows = _csv_rows(gtfs_dir / "stop_times.txt")
    stops_rows = _csv_rows(gtfs_dir / "stops.txt")
    calendar_rows = _csv_rows(gtfs_dir / "calendar.txt")
    shapes_rows = _csv_rows(gtfs_dir / "shapes.txt") if (gtfs_dir / "shapes.txt").exists() else []

    route_ids = {str(row.get("route_id") or "") for row in routes_rows if row.get("route_id")}
    trip_ids = {str(row.get("trip_id") or "") for row in trips_rows if row.get("trip_id")}
    stop_ids = {str(row.get("stop_id") or "") for row in stops_rows if row.get("stop_id")}
    service_ids = {str(row.get("service_id") or "") for row in calendar_rows if row.get("service_id")}
    calendar_date_service_ids = {
        str(row.get("service_id") or "")
        for row in _csv_rows(gtfs_dir / "calendar_dates.txt")
        if row.get("service_id")
    }
    shape_ids = {str(row.get("shape_id") or "") for row in shapes_rows if row.get("shape_id")}

    missing_trip_routes = sorted(
        {
            str(row.get("route_id") or "")
            for row in trips_rows
            if row.get("route_id") and str(row.get("route_id")) not in route_ids
        }
    )
    missing_trip_services = sorted(
        {
            str(row.get("service_id") or "")
            for row in trips_rows
            if row.get("service_id")
            and str(row.get("service_id")) not in service_ids
            and str(row.get("service_id")) not in calendar_date_service_ids
        }
    )
    missing_stop_time_trips = sorted(
        {
            str(row.get("trip_id") or "")
            for row in stop_times_rows
            if row.get("trip_id") and str(row.get("trip_id")) not in trip_ids
        }
    )
    missing_stop_time_stops = sorted(
        {
            str(row.get("stop_id") or "")
            for row in stop_times_rows
            if row.get("stop_id") and str(row.get("stop_id")) not in stop_ids
        }
    )
    missing_trip_shapes = sorted(
        {
            str(row.get("shape_id") or "")
            for row in trips_rows
            if row.get("shape_id") and str(row.get("shape_id")) not in shape_ids
        }
    )

    by_trip: Dict[str, List[Dict[str, str]]] = {}
    for row in stop_times_rows:
        trip_id = str(row.get("trip_id") or "")
        if trip_id:
            by_trip.setdefault(trip_id, []).append(row)

    stop_sequence_errors: List[str] = []
    time_order_errors: List[str] = []
    time_regression_errors: List[str] = []
    for trip_id, rows in by_trip.items():
        sorted_rows = sorted(rows, key=lambda row: int(row.get("stop_sequence") or 0))
        seen_sequences = set()
        prev_departure: Optional[int] = None
        for row in sorted_rows:
            sequence = int(row.get("stop_sequence") or 0)
            if sequence in seen_sequences:
                stop_sequence_errors.append(trip_id)
                break
            seen_sequences.add(sequence)

            arrival = _time_to_seconds(str(row.get("arrival_time") or ""))
            departure = _time_to_seconds(str(row.get("departure_time") or ""))
            if arrival is not None and departure is not None and arrival > departure:
                time_order_errors.append(trip_id)
                break
            current = departure if departure is not None else arrival
            if current is not None and prev_departure is not None and current < prev_departure:
                time_regression_errors.append(trip_id)
                break
            if current is not None:
                prev_departure = current

    missing_coordinates = sum(
        1 for row in stops_rows if not row.get("stop_lat") or not row.get("stop_lon")
    )
    header_only_calendar_dates = file_checks["calendar_dates.txt"]["rows"] == 0
    external_validator = _validate_external_command(gtfs_dir, validator_command)

    errors: List[str] = []
    for name, result in file_checks.items():
        if not result["exists"]:
            errors.append(f"Missing required GTFS file: {name}")
        elif not result["non_empty"]:
            errors.append(f"Empty GTFS file: {name}")
    for key, ok in count_alignment.items():
        if not ok:
            errors.append(f"Count mismatch for {key}")
    if missing_trip_routes:
        errors.append(f"Trips reference unknown routes: {len(missing_trip_routes)}")
    if missing_trip_services:
        errors.append(f"Trips reference unknown services: {len(missing_trip_services)}")
    if missing_stop_time_trips:
        errors.append(f"Stop times reference unknown trips: {len(missing_stop_time_trips)}")
    if missing_stop_time_stops:
        errors.append(f"Stop times reference unknown stops: {len(missing_stop_time_stops)}")
    if missing_trip_shapes:
        errors.append(f"Trips reference unknown shapes: {len(missing_trip_shapes)}")
    if stop_sequence_errors:
        errors.append(f"Duplicate stop_sequence detected in {len(stop_sequence_errors)} trips")
    if time_order_errors:
        errors.append(f"arrival_time > departure_time in {len(time_order_errors)} trips")
    if time_regression_errors:
        errors.append(f"Time regression detected in {len(time_regression_errors)} trips")
    if counts["gtfs"]["services"] == 0:
        errors.append("calendar.txt has zero services")

    warnings: List[str] = list(canonical_summary.get("warnings") or [])
    if header_only_calendar_dates:
        warnings.append("calendar_dates.txt is header-only; exception-day service is not yet modeled.")
    if missing_coordinates:
        warnings.append(f"{missing_coordinates} stop(s) missing coordinates.")
    if external_validator.get("status") == "skipped":
        warnings.append("External MobilityData validation was skipped.")

    snapshot_id = str(canonical_summary.get("snapshot_id") or canonical_dir.name)
    report = {
        "feed_id": TOKYU_ODPT_GTFS_FEED_ID,
        "snapshot_id": snapshot_id,
        "dataset_id": build_dataset_id(TOKYU_ODPT_GTFS_FEED_ID, snapshot_id),
        "canonical_dir": str(canonical_dir),
        "gtfs_dir": str(gtfs_dir),
        "valid": not errors and external_validator.get("status") != "failed",
        "errors": errors,
        "warnings": warnings,
        "required_files": file_checks,
        "count_alignment": count_alignment,
        "counts": counts,
        "references": {
            "missing_trip_routes": missing_trip_routes,
            "missing_trip_services": missing_trip_services,
            "missing_stop_time_trips": missing_stop_time_trips,
            "missing_stop_time_stops": missing_stop_time_stops,
            "missing_trip_shapes": missing_trip_shapes,
        },
        "temporal_checks": {
            "duplicate_stop_sequence_trips": sorted(set(stop_sequence_errors)),
            "arrival_after_departure_trips": sorted(set(time_order_errors)),
            "time_regression_trips": sorted(set(time_regression_errors)),
        },
        "spatial_checks": {
            "missing_coordinate_count": missing_coordinates,
            "shape_count": counts["gtfs"]["shapes"],
        },
        "external_validator": external_validator,
    }

    destination = report_path or (gtfs_dir / "validation_report.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return report
