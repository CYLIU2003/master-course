"""Reaggregate frozen weekly evidence; never call a solver or external API."""

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outcome/2026-09-28_september_presentation/evidence"
OUTPUT = Path(__file__).resolve().parent
STEP_H = 0.25
EFFICIENCY = 0.95
THRESHOLD_KW = 200.0  # Soft experiment tariff threshold, not an equipment limit.
MANIFEST_SHA256 = "52f6b6288ecf9295bad622a4f71de16b2e1cac0094934326e382cecd4de6dd87"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_april_may_comparison(results):
    by_week = {row["week"]: row for row in results}
    april, may = by_week["2025-04-07"], by_week["2025-05-12"]
    fields = ["total_cost", "vehicle_usage_cost_jpy", "electricity_cost", "fuel_cost", "co2_cost",
              "contract_overage_cost", "pv_available_kwh", "grid_import_kwh", "pv_curtailed_kwh",
              "bess_final_kwh", "observed_overage_kwh"]
    difference = {key: may[key] - april[key] for key in fields}
    record = {
        "pair": [april["week"], may["week"]],
        "scope": "Same normalized timetable and fleet parameters; observed monthly plans, not a PV-only controlled counterfactual",
        "difference_may_minus_april": difference,
        "overage_cost_share_of_total_difference_percent": 100 * difference["contract_overage_cost"] / difference["total_cost"],
        "fixed_plan_cost_difference_formula": {
            "intercept_jpy": difference["total_cost"] - difference["contract_overage_cost"],
            "overage_difference_kwh": difference["observed_overage_kwh"],
            "coefficient_jpy_per_overage_kwh": 500,
            "scope": "Accounting identity for these fixed plans, not reoptimization under another coefficient",
        },
    }
    (OUTPUT / "april_may_comparison.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    if hashlib.sha256((SOURCE / "manifest.json").read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Frozen evidence manifest changed; create a new analysis version")
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest.items():
        actual = hashlib.sha256((SOURCE / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Frozen input changed: {relative}")
    results, nights, daily = [], [], []
    for summary in read_csv(SOURCE / "weekly_summary.csv"):
        week = summary["week"]
        folder = SOURCE / week
        energy = read_csv(folder / "energy_15min.csv")
        schedule = read_csv(folder / "vehicle_schedule.csv")
        fleet = read_csv(folder / "fleet.csv")
        physical = json.loads((folder / "physical_validation.json").read_text("utf-8"))
        if not physical.get("accepted"):
            raise ValueError(f"Saved physical report not accepted: {week}")
        total = lambda key: sum(float(row[key]) for row in energy)
        grid, direct, to_bess, discharge, curtail = (
            total(key) for key in ("grid_import_kwh", "pv_to_bus_kwh", "pv_to_bess_kwh",
                                  "bess_to_bus_kwh", "pv_curtailed_kwh")
        )
        balance = max(abs(float(r["bus_charge_kwh"]) - float(r["grid_import_kwh"])
                          - float(r["pv_to_bus_kwh"]) - float(r["bess_to_bus_kwh"])) for r in energy)
        if balance > 1e-6:
            raise ValueError(f"Power balance mismatch: {week}")
        first = energy[0]
        initial = (float(first["bess_soc_end_kwh"]) + float(first["bess_to_bus_kwh"]) / EFFICIENCY
                   - EFFICIENCY * float(first["pv_to_bess_kwh"]))
        final = float(energy[-1]["bess_soc_end_kwh"])
        stock_equivalent = EFFICIENCY * (initial - final)
        storage_residual = discharge - EFFICIENCY**2 * to_bess - stock_equivalent
        if abs(storage_residual) > 1e-5:
            raise ValueError(f"BESS aggregate balance mismatch: {week}")
        over = sum(max(0, float(r["grid_import_kwh"]) - THRESHOLD_KW * STEP_H) for r in energy)
        if abs(over * 500 - float(summary["contract_overage_cost"])) > 1e-6:
            raise ValueError(f"Overage model cost mismatch: {week}")
        components = sum(float(summary[k]) for k in (
            "vehicle_usage_cost_jpy", "electricity_cost", "fuel_cost", "co2_cost", "contract_overage_cost"))
        if abs(components - float(summary["total_cost"])) > 1e-6:
            raise ValueError(f"Cost decomposition mismatch: {week}")
        night_by_date = defaultdict(list)
        for row in energy:
            stamp = datetime.fromisoformat(row["interval_start_jst"])
            if stamp.hour < 6:
                night_by_date[stamp.date().isoformat()].append(row)
        day_by_date = defaultdict(list)
        for row in energy:
            day_by_date[row["interval_start_jst"][:10]].append(row)
        day_initial = initial
        for day, rows in day_by_date.items():
            day_total = lambda key: sum(float(r[key]) for r in rows)
            day_final = float(rows[-1]["bess_soc_end_kwh"])
            daily.append({"week": week, "date": day,
                          "scope": "service_week" if (datetime.fromisoformat(day) - datetime.fromisoformat(week)).days < 7 else "overnight_tail",
                          "observed_hours": len(rows) * STEP_H,
                          "pv_available_kwh": sum(day_total(k) for k in ["pv_to_bus_kwh", "pv_to_bess_kwh", "pv_curtailed_kwh"]),
                          "grid_import_kwh": day_total("grid_import_kwh"),
                          "pv_curtailed_kwh": day_total("pv_curtailed_kwh"),
                          "bess_initial_kwh": day_initial, "bess_final_kwh": day_final})
            day_initial = day_final
        night_grid = sum(float(r["grid_import_kwh"]) for rows in night_by_date.values() for r in rows)
        night_relaxed = 0.0
        for day, rows in night_by_date.items():
            volume = sum(float(r["grid_import_kwh"]) for r in rows)
            relaxed = max(0, volume - THRESHOLD_KW * STEP_H * len(rows))
            night_relaxed += relaxed
            nights.append({"week": week, "date": day, "observed_hours_00_06": len(rows) * STEP_H,
                           "observed_grid_kwh": volume,
                           "observed_overage_kwh": sum(max(0, float(r["grid_import_kwh"]) - 50) for r in rows),
                           "relaxed_fixed_volume_excess_lower_bound_kwh": relaxed})
        signature_fields = ["day_index", "template_trip_id", "source_departure", "source_arrival",
                            "origin_stop_id", "destination_stop_id", "operator_id", "distance_km", "day_type"]
        signatures = sorted(tuple(r[k] for k in signature_fields) for r in schedule)
        fleet_parameters = sorted(({k: v for k, v in r.items() if k != "used_in_week"} for r in fleet),
                                  key=lambda r: r["id"])
        row = {k: summary[k] for k in ["week", "git_sha", "trips", "service_km", "evaluation_status",
                                      "fuel_cost_final_source", "integrated_weekly_gap"]}
        row.update({k: float(summary[k]) for k in ["total_cost", "vehicle_usage_cost_jpy", "electricity_cost",
                     "fuel_cost", "co2_cost", "contract_overage_cost", "peak_grid_kw", "used_vehicle_day_count"]})
        row.update(non_vehicle_model_cost_jpy=float(summary["total_cost"]) - float(summary["vehicle_usage_cost_jpy"]),
                   pv_available_kwh=direct + to_bess + curtail, pv_to_bus_kwh=direct, pv_to_bess_kwh=to_bess,
                   bess_to_bus_kwh=discharge, bus_charge_kwh=total("bus_charge_kwh"),
                   grid_import_kwh=grid, night_grid_share_percent=100 * night_grid / grid,
                   pv_curtailed_kwh=curtail, bess_initial_kwh=initial, bess_final_kwh=final,
                   bess_net_stock_bus_equivalent_kwh=stock_equivalent,
                   bess_aggregate_residual_kwh=storage_residual, supply_max_residual_kwh=balance,
                   observed_overage_kwh=over,
                   relaxed_night_fixed_volume_excess_lower_bound_kwh=night_relaxed,
                   normalized_timetable_hash=digest(signatures), fleet_parameter_hash=digest(fleet_parameters))
        results.append(row)
    for filename, rows in [("monthly_mechanism_metrics.csv", results), ("night_energy_relaxation.csv", nights),
                           ("daily_mechanism_metrics.csv", daily)]:
        with (OUTPUT / filename).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    write_april_may_comparison(results)
    record = {"date_jst": "2026-10-03", "source_files_hash_verified": len(manifest),
              "weeks": len(results), "saved_physical_reports_accepted": len(results), "new_solver_run": False,
              "scope": "CSV reaggregation and saved report inspection; not native run revalidation",
              "normalized_timetable_hash_count": len({r["normalized_timetable_hash"] for r in results}),
              "fleet_parameter_hash_count": len({r["fleet_parameter_hash"] for r in results}),
              "night_relaxation_scope": "Each observed 00-06 segment holds executed grid energy fixed; relaxes charger, availability and SOC deadlines. Not a feasible alternative, solver bound, or weekly optimality bound.",
              "efficiency_basis": "Frozen scenario eta_charge=eta_discharge=0.95, bus-side BESS discharge",
              "source_manifest_sha256": hashlib.sha256((SOURCE / "manifest.json").read_bytes()).hexdigest()}
    (OUTPUT / "analysis_verification.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
