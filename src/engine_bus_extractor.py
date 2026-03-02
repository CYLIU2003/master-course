"""
engine_bus_extractor.py

Phase 1: Extract, normalize, and compute derived indicators from JH25-mode
diesel bus Excel files (bus_isuzu_jh25.xlsx, bus_hino_jh25.xlsx,
mitsubishifuso_bus_jh25.xlsx).

All source files live in constant/; outputs go to data/engine_bus/output/.

Usage:
    from src.engine_bus_extractor import run_extraction
    run_extraction()
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIESEL_ENERGY_KWH_PER_L: float = 9.8

# Map column position (0-based) → standard field name.
# The sheet structure is identical in all three files:
#   col 0  : 車名 (manufacturer label – present only on first row of each group)
#   col 1  : 通称名 (vehicle common name – present only on first row of group)
#   col 2  : 車名 alias / sub-model name (sometimes populated)
#   col 3  : 型式 model_code
#   col 4  : 原動機型式 engine_model
#   col 5  : 総排気量(L)
#   col 6  : 最大トルク(N-m)
#   col 7  : 最高出力(kW)
#   col 8  : 変速装置 transmission
#   col 9  : 車両重量(kg)
#   col 10 : 車両総重量(kg)
#   col 11 : 最大積載量/乗車定員
#   col 12 : 自動車の構造 (bus_category)
#   col 13 : 燃費値(km/L)
#   col 14 : CO2排出量(g-CO2/km)
#   col 15 : 令和7年度燃費基準値(km/L)
#   col 16 : 主要燃費改善対策
#   col 17 : 主要排出ガス対策
#   col 18 : 車輪配列
#   col 19 : その他・備考
#   col 20 : 低排出ガス認定レベル (reference – not always present)
#   col 21 : 燃費基準達成レベル / R7基準 (sometimes blank → col 23)
#   col 22 : (spare / blank in isuzu & fuso; OEM note in hino)
#   col 23 : R7達成レベル (%)

COL_MAP: dict[int, str] = {
    0: "manufacturer_raw",
    1: "vehicle_name_raw",
    2: "vehicle_name_alias",
    3: "model_code",
    4: "engine_model",
    5: "displacement_L",
    6: "max_torque_Nm",
    7: "max_power_kW",
    8: "transmission",
    9: "vehicle_weight_kg",
    10: "gross_vehicle_weight_kg",
    11: "passenger_capacity",
    12: "structure_type_raw",
    13: "fuel_economy_km_per_L",
    14: "co2_g_per_km",
    15: "fuel_standard_km_per_L",
    16: "fuel_saving_measures",
    17: "emission_measures",
    18: "wheel_arrangement",
    19: "notes",
    20: "low_emission_certification",
    21: "fuel_standard_achievement_level",
    22: "_spare",
    23: "fuel_standard_r7_pct",
}

# Rows 0-7 (0-indexed) are header / title rows; data starts at row 8.
DATA_START_ROW: int = 8

# Japanese bus-category text → normalized English key
CATEGORY_MAP: dict[str, str] = {
    "一般バス": "coach_bus",
    "路線バス": "route_bus",
    # fallback substrings
    "一般": "coach_bus",
    "路線": "route_bus",
}

# Manufacturer identification: look for these substrings in garbled column 0
MFR_LABEL_MAP: dict[str, str] = {
    "bus_isuzu_jh25.xlsx": "Isuzu",
    "bus_hino_jh25.xlsx": "Hino",
    "mitsubishifuso_bus_jh25.xlsx": "MitsubishiFuso",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Walk up from this file to find the project root (contains src/ and .git)."""
    here = Path(__file__).resolve().parent
    for p in [here, *here.parents]:
        if (p / "src").is_dir() and (p / ".git").is_dir():
            return p
        if (p / "src").is_dir() and (p / "constant").is_dir():
            return p
    return here.parent


def _to_float(val: Any) -> float | None:
    """Convert a cell value to float; return None if not convertable."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(str(val).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def _to_int(val: Any) -> int | None:
    f = _to_float(val)
    if f is None:
        return None
    return int(round(f))


def _clean_str(val: Any) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    # collapse internal newlines and excessive spaces
    s = re.sub(r"\s+", " ", s)
    return s if s else None


def _normalize_category(raw: str | None) -> str:
    if raw is None:
        return "unknown"
    for jp, en in CATEGORY_MAP.items():
        if jp in raw:
            return en
    return "unknown"


def _null_count(rec: dict) -> int:
    numeric_fields = [
        "fuel_economy_km_per_L",
        "co2_g_per_km",
        "displacement_L",
        "max_torque_Nm",
        "max_power_kW",
        "vehicle_weight_kg",
        "gross_vehicle_weight_kg",
        "passenger_capacity",
    ]
    return sum(1 for f in numeric_fields if rec.get(f) is None)


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------


def extract_file(xlsx_path: Path, manufacturer: str) -> list[dict]:
    """
    Read the '3-1' sheet of *xlsx_path* and return a list of raw record dicts,
    one per data row.  Merged cells in columns 0, 1, 2 are forward-filled
    conservatively (only when model_code is populated in the current row).
    """
    df = pd.read_excel(
        xlsx_path, sheet_name="3-1", header=None, engine="openpyxl", dtype=object
    )

    records: list[dict] = []
    prev_mfr_raw: str | None = None
    prev_name_raw: str | None = None
    prev_alias: str | None = None

    for row_idx in range(DATA_START_ROW, len(df)):
        row = df.iloc[row_idx]

        # Skip rows that look like footnotes (no model_code)
        model_code_raw = _clean_str(row.iloc[3]) if len(row) > 3 else None
        if not model_code_raw:
            continue

        # ---- forward-fill manufacturer / name from previous row ----
        mfr_raw = _clean_str(row.iloc[0]) if len(row) > 0 else None
        name_raw = _clean_str(row.iloc[1]) if len(row) > 1 else None
        alias_raw = _clean_str(row.iloc[2]) if len(row) > 2 else None

        imputed: list[str] = []

        if mfr_raw:
            prev_mfr_raw = mfr_raw
        elif prev_mfr_raw:
            mfr_raw = prev_mfr_raw
            imputed.append("manufacturer_raw")

        if name_raw:
            prev_name_raw = name_raw
        elif prev_name_raw:
            name_raw = prev_name_raw
            imputed.append("vehicle_name_raw")

        if alias_raw:
            prev_alias = alias_raw
        # alias is NOT forward-filled – it's specific to each sub-entry

        # ---- raw value extraction ----
        def col(i: int) -> Any:
            return row.iloc[i] if i < len(row) else None

        displacement_raw = col(5)
        torque_raw = col(6)
        power_raw = col(7)
        transmission_raw = col(8)
        vw_raw = col(9)
        gvw_raw = col(10)
        cap_raw = col(11)
        structure_raw = col(12)
        fuel_raw = col(13)
        co2_raw = col(14)
        std_raw = col(15)
        fuel_saving_raw = col(16)
        emission_raw = col(17)
        wheel_raw = col(18)
        notes_raw = col(19)
        low_em_raw = col(20)
        achieve_raw = col(21)
        r7_raw = col(23)

        # ---- typed conversions ----
        displacement = _to_float(displacement_raw)
        max_torque = _to_float(torque_raw)
        max_power = _to_float(power_raw)
        vehicle_weight = _to_int(vw_raw)
        gvw = _to_int(gvw_raw)
        passenger_cap = _to_int(cap_raw)
        fuel_economy = _to_float(fuel_raw)
        co2 = _to_float(co2_raw)
        fuel_std = _to_float(std_raw)
        achievement_r7 = _to_float(r7_raw) or _to_float(achieve_raw)

        structure_str = _clean_str(structure_raw)
        bus_category = _normalize_category(structure_str)

        # ---- raw text backups for non-numeric originals ----
        raw_backup: dict[str, str] = {}
        for field, raw_val in [
            ("max_torque_Nm", torque_raw),
            ("max_power_kW", power_raw),
            ("passenger_capacity", cap_raw),
        ]:
            if _to_float(raw_val) is None and raw_val is not None:
                raw_backup[field] = str(raw_val)

        rec: dict = {
            # identification
            "manufacturer": manufacturer,
            "vehicle_name": _clean_str(name_raw),
            "vehicle_name_alias": _clean_str(alias_raw),
            "model_code": model_code_raw,
            "bus_category": bus_category,
            "source_file": xlsx_path.name,
            "source_sheet": "3-1",
            "source_row": row_idx + 1,  # 1-based Excel row
            # powertrain
            "engine_model": _clean_str(col(4)),
            "displacement_L": displacement,
            "max_torque_Nm": _to_float(torque_raw),
            "max_power_kW": _to_float(power_raw),
            "transmission": _clean_str(transmission_raw),
            # mass / capacity
            "vehicle_weight_kg": vehicle_weight,
            "gross_vehicle_weight_kg": gvw,
            "passenger_capacity": passenger_cap,
            "structure_type": structure_str,
            "wheel_arrangement": _clean_str(wheel_raw),
            # efficiency
            "fuel_economy_km_per_L": fuel_economy,
            "co2_g_per_km": co2,
            "fuel_standard_km_per_L": fuel_std,
            "fuel_standard_achievement_r7_pct": achievement_r7,
            "low_emission_certification": _clean_str(low_em_raw),
            "fuel_saving_measures": _clean_str(fuel_saving_raw),
            "emission_measures": _clean_str(emission_raw),
            "notes": _clean_str(notes_raw),
            # metadata
            "imputed_fields": imputed,
            "raw_text_backup": raw_backup,
        }

        # ---- quality flags ----
        rec["needs_manual_review"] = _null_count(rec) >= 4

        records.append(rec)

    return records


# ---------------------------------------------------------------------------
# Derived indicators
# ---------------------------------------------------------------------------


def compute_derived(rec: dict) -> dict:
    """Add derived fields to a (shallow copy of) *rec*."""
    out = dict(rec)
    fe = rec.get("fuel_economy_km_per_L")
    cap = rec.get("passenger_capacity")
    co2 = rec.get("co2_g_per_km")

    if fe and fe > 0:
        out["diesel_consumption_L_per_km"] = round(1.0 / fe, 6)
        out["diesel_consumption_L_per_100km"] = round(100.0 / fe, 4)
        out["equivalent_energy_kWh_per_km"] = round(
            (1.0 / fe) * DIESEL_ENERGY_KWH_PER_L, 4
        )
    else:
        out["diesel_consumption_L_per_km"] = None
        out["diesel_consumption_L_per_100km"] = None
        out["equivalent_energy_kWh_per_km"] = None

    if fe and fe > 0 and cap and cap > 0:
        out["diesel_L_per_pax_km"] = round((1.0 / fe) / cap, 8)
    else:
        out["diesel_L_per_pax_km"] = None

    if co2 and co2 > 0 and cap and cap > 0:
        out["co2_g_per_pax_km"] = round(co2 / cap, 4)
    else:
        out["co2_g_per_pax_km"] = None

    # Consistency check: |1/fe - consumption| should be < 0.001
    cons = out.get("diesel_consumption_L_per_km")
    if fe and fe > 0 and cons is not None:
        out["consistency_ok"] = abs(cons - (1.0 / fe)) < 1e-4
    else:
        out["consistency_ok"] = None

    return out


# ---------------------------------------------------------------------------
# Normalization (clean up field names already done in extract; just ensure
# numeric types are correct and categories are English)
# ---------------------------------------------------------------------------


def normalize_records(raw_records: list[dict]) -> list[dict]:
    """Return a cleaned list; numeric fields cast, categories in English."""
    normalized = []
    for rec in raw_records:
        n = compute_derived(rec)
        normalized.append(n)
    return normalized


# ---------------------------------------------------------------------------
# Simulation vehicle library selection
# ---------------------------------------------------------------------------


def _vehicle_id(mfr: str, model_code: str, idx: int) -> str:
    prefix = mfr.lower().replace(" ", "_")
    code = re.sub(r"[^a-zA-Z0-9]", "_", model_code).lower()
    return f"{prefix}_{code}_{idx:02d}"


def build_simulation_library(normalized: list[dict]) -> list[dict]:
    """
    Build the simulation vehicle library.  For each (manufacturer, bus_category)
    group produce three representative entries:
        - representative : closest to median fuel_economy_km_per_L
        - conservative   : lowest fuel_economy (highest CO2)
        - best           : highest fuel_economy
    Only include records that pass basic quality checks.
    """
    # Filter: must have fuel_economy > 0 and co2 > 0
    valid = [
        r
        for r in normalized
        if (r.get("fuel_economy_km_per_L") or 0) > 0
        and (r.get("co2_g_per_km") or 0) > 0
    ]

    # Group
    groups: dict[tuple, list[dict]] = {}
    for r in valid:
        key = (r["manufacturer"], r["bus_category"])
        groups.setdefault(key, []).append(r)

    library: list[dict] = []
    idx = 1

    for (mfr, cat), members in sorted(groups.items()):
        fes = [m["fuel_economy_km_per_L"] for m in members]
        median_fe = statistics.median(fes)

        # representative: closest to median
        rep = min(members, key=lambda m: abs(m["fuel_economy_km_per_L"] - median_fe))
        # conservative: worst (lowest fe = highest consumption)
        cons = min(members, key=lambda m: m["fuel_economy_km_per_L"])
        # best: highest fe
        best = max(members, key=lambda m: m["fuel_economy_km_per_L"])

        for selection_mode, candidate in [
            ("representative", rep),
            ("conservative", cons),
            ("best_efficiency", best),
        ]:
            entry: dict = {
                "vehicle_id": _vehicle_id(mfr, candidate["model_code"], idx),
                "vehicle_type": "engine_bus",
                "selection_mode": selection_mode,
                "manufacturer": candidate["manufacturer"],
                "vehicle_name": candidate.get("vehicle_name"),
                "model_code": candidate["model_code"],
                "bus_category": candidate["bus_category"],
                "passenger_capacity": candidate.get("passenger_capacity"),
                "vehicle_weight_kg": candidate.get("vehicle_weight_kg"),
                "gross_vehicle_weight_kg": candidate.get("gross_vehicle_weight_kg"),
                "engine_model": candidate.get("engine_model"),
                "displacement_L": candidate.get("displacement_L"),
                "max_power_kW": candidate.get("max_power_kW"),
                "max_torque_Nm": candidate.get("max_torque_Nm"),
                "transmission": candidate.get("transmission"),
                "fuel_economy_km_per_L": candidate.get("fuel_economy_km_per_L"),
                "diesel_consumption_L_per_km": candidate.get(
                    "diesel_consumption_L_per_km"
                ),
                "diesel_consumption_L_per_100km": candidate.get(
                    "diesel_consumption_L_per_100km"
                ),
                "co2_g_per_km": candidate.get("co2_g_per_km"),
                "co2_g_per_pax_km": candidate.get("co2_g_per_pax_km"),
                "equivalent_energy_kWh_per_km": candidate.get(
                    "equivalent_energy_kWh_per_km"
                ),
                "fuel_standard_km_per_L": candidate.get("fuel_standard_km_per_L"),
                "fuel_standard_achievement_r7_pct": candidate.get(
                    "fuel_standard_achievement_r7_pct"
                ),
                "wheel_arrangement": candidate.get("wheel_arrangement"),
                "source": {
                    "file": candidate["source_file"],
                    "sheet": candidate["source_sheet"],
                    "row": candidate["source_row"],
                },
            }
            library.append(entry)
            idx += 1

    return library


# ---------------------------------------------------------------------------
# Markdown summary
# ---------------------------------------------------------------------------


def build_markdown_summary(normalized: list[dict]) -> str:
    lines: list[str] = [
        "# Engine Bus Data Summary (JH25 Mode)",
        "",
        f"**Total records extracted:** {len(normalized)}",
        "",
    ]

    # Per-manufacturer stats
    mfrs = sorted({r["manufacturer"] for r in normalized})
    for mfr in mfrs:
        subset = [r for r in normalized if r["manufacturer"] == mfr]
        fes = [
            r["fuel_economy_km_per_L"] for r in subset if r.get("fuel_economy_km_per_L")
        ]
        co2s = [r["co2_g_per_km"] for r in subset if r.get("co2_g_per_km")]
        cats = sorted({r["bus_category"] for r in subset})
        lines += [
            f"## {mfr}",
            f"- Records: {len(subset)}",
            f"- Bus categories: {', '.join(cats)}",
            f"- Fuel economy range (km/L): {min(fes):.2f} – {max(fes):.2f}"
            if fes
            else "- Fuel economy: N/A",
            f"- CO2 range (g/km): {min(co2s):.1f} – {max(co2s):.1f}"
            if co2s
            else "- CO2: N/A",
            "",
        ]

    # Main table
    lines += [
        "## All Records",
        "",
        "| manufacturer | vehicle_name | model_code | bus_category | "
        "capacity | GVW_kg | fuel_km_per_L | CO2_g_per_km | power_kW | torque_Nm |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in normalized:

        def fmt(v: Any, digits: int = 0) -> str:
            if v is None:
                return "—"
            if digits:
                return f"{float(v):.{digits}f}"
            return str(v)

        lines.append(
            f"| {fmt(r.get('manufacturer'))} "
            f"| {fmt(r.get('vehicle_name'))} "
            f"| {fmt(r.get('model_code'))} "
            f"| {fmt(r.get('bus_category'))} "
            f"| {fmt(r.get('passenger_capacity'))} "
            f"| {fmt(r.get('gross_vehicle_weight_kg'))} "
            f"| {fmt(r.get('fuel_economy_km_per_L'), 2)} "
            f"| {fmt(r.get('co2_g_per_km'), 1)} "
            f"| {fmt(r.get('max_power_kW'))} "
            f"| {fmt(r.get('max_torque_Nm'))} |"
        )

    lines.append("")

    # Needs-review list
    review = [r for r in normalized if r.get("needs_manual_review")]
    if review:
        lines += [
            "## Records Flagged for Manual Review",
            "",
            "| model_code | source_file | source_row |",
            "|---|---|---:|",
        ]
        for r in review:
            lines.append(
                f"| {r.get('model_code')} "
                f"| {r.get('source_file')} "
                f"| {r.get('source_row')} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_extraction(
    constant_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict:
    """
    Run full Phase 1 extraction pipeline.

    Returns a dict with keys:
        raw, normalized, simulation_library
    Also writes 4 files to *output_dir*.
    """
    root = _project_root()
    if constant_dir is None:
        constant_dir = root / "constant"
    if output_dir is None:
        output_dir = root / "data" / "engine_bus" / "output"

    output_dir.mkdir(parents=True, exist_ok=True)

    source_files = [
        ("bus_isuzu_jh25.xlsx", "Isuzu"),
        ("bus_hino_jh25.xlsx", "Hino"),
        ("mitsubishifuso_bus_jh25.xlsx", "MitsubishiFuso"),
    ]

    # ---- Phase 1a: raw extraction ----
    raw_records: list[dict] = []
    for fname, mfr in source_files:
        path = constant_dir / fname
        if not path.exists():
            print(f"[WARN] {path} not found – skipping")
            continue
        recs = extract_file(path, mfr)
        print(f"[INFO] {fname}: extracted {len(recs)} records")
        raw_records.extend(recs)

    # ---- Phase 1b: normalization + derived indicators ----
    normalized = normalize_records(raw_records)

    # ---- Phase 1c: simulation library ----
    sim_library = build_simulation_library(normalized)

    # ---- Phase 1d: Markdown summary ----
    md_summary = build_markdown_summary(normalized)

    # ---- Write outputs ----
    _write_json(output_dir / "engine_bus_raw.json", raw_records)
    _write_json(output_dir / "engine_bus_normalized.json", normalized)
    _write_json(output_dir / "engine_bus_simulation_library.json", sim_library)
    (output_dir / "engine_bus_summary.md").write_text(md_summary, encoding="utf-8")

    print(
        f"[INFO] Wrote {len(raw_records)} raw, {len(normalized)} normalized, "
        f"{len(sim_library)} library entries to {output_dir}"
    )

    return {
        "raw": raw_records,
        "normalized": normalized,
        "simulation_library": sim_library,
    }


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[INFO] Written: {path} ({len(data)} records)")


# ---------------------------------------------------------------------------
# CLI shim
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_extraction()
