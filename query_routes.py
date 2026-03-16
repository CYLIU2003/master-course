"""Simple CLI to inspect route records without scenario dependencies."""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


CSV_PATH = os.path.join("data", "route_master", "routes.csv")
NORMALIZED_PATH = os.path.join("data", "catalog-fast", "normalized", "routes.jsonl")
CANONICAL_GLOB = os.path.join("data", "tokyubus", "canonical", "*", "routes.jsonl")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query route master records.")
    parser.add_argument(
        "--source",
        choices=["auto", "csv", "normalized", "canonical"],
        default="auto",
        help="Route source to load (default: auto).",
    )
    parser.add_argument(
        "--q",
        default="",
        help="Case-insensitive keyword filter for code/name/label/start/end/id.",
    )
    parser.add_argument(
        "--operator",
        default="",
        help="Filter by operator id if operator field exists.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="Maximum rows to print (default: 40).",
    )
    return parser.parse_args(argv)


def latest_canonical_path() -> Optional[str]:
    candidates = [path for path in glob.glob(CANONICAL_GLOB) if os.path.isfile(path)]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def choose_source(source: str) -> Optional[str]:
    if source == "csv":
        return CSV_PATH if os.path.isfile(CSV_PATH) else None
    if source == "normalized":
        return NORMALIZED_PATH if os.path.isfile(NORMALIZED_PATH) else None
    if source == "canonical":
        return latest_canonical_path()

    if os.path.isfile(CSV_PATH):
        return CSV_PATH
    if os.path.isfile(NORMALIZED_PATH):
        return NORMALIZED_PATH
    return latest_canonical_path()


def load_csv(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def first_non_empty(record: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = record.get(key)
        text = as_text(value).strip()
        if text:
            return text
    return ""


def route_operator(record: Dict[str, Any]) -> str:
    return first_non_empty(record, ("operator_id", "operatorId", "operator"))


def match_query(record: Dict[str, Any], keyword: str) -> bool:
    if not keyword:
        return True
    text = " ".join(
        [
            first_non_empty(record, ("route_code", "routeCode", "code")),
            first_non_empty(record, ("route_label", "routeLabel", "label")),
            first_non_empty(record, ("route_name", "routeName", "name")),
            first_non_empty(record, ("start_stop_name", "start", "origin", "from")),
            first_non_empty(record, ("end_stop_name", "end", "destination", "to")),
            first_non_empty(record, ("route_id", "id", "routeId")),
        ]
    ).lower()
    return keyword.lower() in text


def match_operator(record: Dict[str, Any], operator: str) -> bool:
    if not operator:
        return True
    value = route_operator(record)
    if not value:
        return True
    return value == operator


def project_row(index: int, record: Dict[str, Any]) -> Tuple[str, str, str, str, str, str, str, str]:
    route_id = first_non_empty(record, ("route_id", "id", "routeId"))
    route_code = first_non_empty(record, ("route_code", "routeCode", "code"))
    route_label = first_non_empty(record, ("route_label", "route_name", "routeLabel", "routeName", "name", "label"))
    start = first_non_empty(record, ("start_stop_name", "start", "origin", "from"))
    end = first_non_empty(record, ("end_stop_name", "end", "destination", "to"))
    operator = route_operator(record)
    trip_count = first_non_empty(record, ("tripCount", "trip_count", "trips", "trip_count_total"))
    return (
        str(index),
        route_id,
        route_code,
        route_label,
        start,
        end,
        operator,
        trip_count,
    )


def print_table(rows: List[Tuple[str, str, str, str, str, str, str, str]]) -> None:
    headers = ["idx", "route_id", "route_code", "route_label", "start", "end", "operator", "tripCount"]
    print("\t".join(headers))
    for row in rows:
        clipped = [cell if len(cell) <= 96 else cell[:93] + "..." for cell in row]
        print("\t".join(clipped))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.limit <= 0:
        print("Error: --limit must be a positive integer.", file=sys.stderr)
        return 2

    source_path = choose_source(args.source)
    if not source_path:
        print(
            "Error: no route source found. Checked data/route_master/routes.csv, "
            "data/catalog-fast/normalized/routes.jsonl, and data/tokyubus/canonical/*/routes.jsonl.",
            file=sys.stderr,
        )
        return 1

    try:
        if source_path.lower().endswith(".csv"):
            routes = load_csv(source_path)
        else:
            routes = load_jsonl(source_path)
    except (OSError, ValueError) as exc:
        print(f"Error: failed to load routes from {source_path}: {exc}", file=sys.stderr)
        return 1

    filtered = [r for r in routes if match_query(r, args.q) and match_operator(r, args.operator)]

    print(f"Source: {source_path}")
    print(f"Total matches: {len(filtered)}")

    if not filtered:
        print("Error: no matching routes found for the given filters.", file=sys.stderr)
        return 1

    limit = min(args.limit, len(filtered))
    table_rows = [project_row(i + 1, filtered[i]) for i in range(limit)]
    print_table(table_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

