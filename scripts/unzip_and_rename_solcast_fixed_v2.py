#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

COORD_TO_DEPOT: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("35.653631", "139.672728"): ("awashima", "淡島営業所"),
    ("35.638233", "139.684341"): ("shimouma", "下馬営業所"),
    ("35.635147", "139.646243"): ("tsurumaki", "弦巻営業所"),
    ("35.617739", "139.635778"): ("seta", "瀬田営業所"),
    ("35.627679", "139.694185"): ("meguro", "目黒営業所"),
    ("35.602506", "139.713295"): ("ebara", "荏原営業所"),
    ("35.576938", "139.715368"): ("ikegami", "池上営業所"),
    ("35.608029", "139.615168"): ("takatsu", "高津営業所"),
    ("35.530757", "139.611279"): ("nippa", "新羽営業所"),
    ("35.531741", "139.517907"): ("aobadai", "青葉台営業所"),
    ("35.582544", "139.522771"): ("nijigaoka", "虹が丘営業所"),
    ("35.561217", "139.605167"): ("higashiyamata", "東山田営業所"),
}

COORD_ALIASES: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("35.63823305555555", "139.6843413888889"): ("35.638233", "139.684341"),
    ("35.63514694444444", "139.6462427777778"): ("35.635147", "139.646243"),
    ("35.5769382", "139.7153683"): ("35.576938", "139.715368"),
}

ZIP_RE = re.compile(
    r"^csv_(?P<lat>-?\d+(?:\.\d+)?)_(?P<lon>-?\d+(?:\.\d+)?)_.*?PT(?P<minutes>\d+)M(?: \(\d+\))?\.zip$",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class ZipInfoResult:
    zip_path: Path
    lat: str
    lon: str
    minutes: int
    depot_id: str
    depot_name: str

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def normalize_coord_key(lat: str, lon: str) -> Tuple[str, str]:
    key = (lat, lon)
    return COORD_ALIASES.get(key, key)

def parse_zip_name(zip_path: Path) -> Optional[ZipInfoResult]:
    m = ZIP_RE.match(zip_path.name)
    if not m:
        return None
    lat = m.group("lat")
    lon = m.group("lon")
    minutes = int(m.group("minutes"))
    norm_key = normalize_coord_key(lat, lon)
    if norm_key not in COORD_TO_DEPOT:
        return None
    depot_id, depot_name = COORD_TO_DEPOT[norm_key]
    return ZipInfoResult(zip_path, norm_key[0], norm_key[1], minutes, depot_id, depot_name)

def find_first_csv_bytes(zf: zipfile.ZipFile) -> Tuple[str, bytes]:
    csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
    if not csv_names:
        raise ValueError("ZIP archive does not contain any CSV file.")
    name = csv_names[0]
    return name, zf.read(name)

def infer_year_month(csv_bytes: bytes) -> Tuple[int, int]:
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    first_period_end = None
    for row in reader:
        first_period_end = (row.get("period_end") or "").strip()
        if first_period_end:
            break
    if not first_period_end:
        raise ValueError("CSV does not contain a usable period_end column.")
    dt = datetime.fromisoformat(first_period_end)
    return dt.year, dt.month

def unique_output_path(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path
    stem = base_path.stem
    suffix = base_path.suffix
    parent = base_path.parent
    idx = 2
    while True:
        candidate = parent / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1

def process_zip(info: ZipInfoResult, out_dir: Path, overwrite: bool = False) -> Tuple[str, Path]:
    with zipfile.ZipFile(info.zip_path, "r") as zf:
        _inner_name, csv_bytes = find_first_csv_bytes(zf)

    year, month = infer_year_month(csv_bytes)
    out_name = f"{info.depot_id}_{year}_{month:02d}_{info.minutes}min.csv"
    out_path = out_dir / out_name

    if out_path.exists():
        existing_hash = sha256_bytes(out_path.read_bytes())
        new_hash = sha256_bytes(csv_bytes)
        if existing_hash == new_hash:
            return "duplicate_same_content", out_path
        if overwrite:
            out_path.write_bytes(csv_bytes)
            return "overwritten", out_path
        out_path = unique_output_path(out_path)

    out_path.write_bytes(csv_bytes)
    return "written", out_path

def iter_zip_files(download_dir: Path) -> Iterable[Path]:
    yield from sorted(download_dir.glob("*.zip"))

def main() -> int:
    parser = argparse.ArgumentParser(description="Extract and rename Solcast ZIP downloads.")
    parser.add_argument(
        "--downloads",
        type=Path,
        default=Path(r"C:\Users\RTDS_admin\Downloads"),
        help=r"Folder containing Solcast ZIP downloads. Default: C:\Users\RTDS_admin\Downloads",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path(r"C:\master-course"),
        help=r"master-course working directory. Default: C:\master-course",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help=r"Optional explicit output folder. Defaults to <workdir>\data\external\solcast_raw",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    downloads = args.downloads
    out_dir = args.outdir or (args.workdir / "data" / "external" / "solcast_raw")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not downloads.exists():
        print(f"[ERROR] Downloads folder not found: {downloads}")
        return 1

    matched = 0
    skipped_unknown = 0

    for zip_path in iter_zip_files(downloads):
        info = parse_zip_name(zip_path)
        if info is None:
            skipped_unknown += 1
            print(f"[SKIP] Unrecognized or unmapped ZIP: {zip_path.name}")
            continue
        matched += 1
        try:
            status, out_path = process_zip(info, out_dir, overwrite=args.overwrite)
            print(f"[{status.upper()}] {zip_path.name} -> {out_path}")
        except Exception as exc:
            print(f"[ERROR] Failed to process {zip_path.name}: {exc}")

    print()
    print(f"Processed ZIPs matched to depots: {matched}")
    print(f"Skipped ZIPs (unknown pattern/coords): {skipped_unknown}")
    print(f"Output folder: {out_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
