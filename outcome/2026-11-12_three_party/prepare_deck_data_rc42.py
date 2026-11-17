"""Collect the rc42 (19dc0780) pillar A numbers for the poster and deck, one tariff series at a time. DIAGNOSTIC.

rc42 reruns every case of both tariff series with uniform settings (MIP gap 5 %, hourly re-plan 300 s):
  et: energy charge 17.43 JPY/kWh in the model; the weekly basic charge is a constant added to the result
      (90 kW 44,664 / 200 kW 99,254 / 400 kW 198,508 / 900 kW 446,642 JPY per week) and is kept as its own field.
  ct: 30 JPY/kWh all-inclusive (comparison series); no basic charge is added.
Case directories: output/midterm_20261128/rc42/<s><b|i><limit>/<week> (b = BEV-priority, i = ICE-priority start).
Three summer cases failed day-ahead with Stage 2 memory_limit at the 14 GiB task budget (etb200, ctb900, ctb090);
their single 24 GiB rerun (same release, prepared input and overrides) is rc42m24/<case>m24/<week>. The failed
attempts are listed in `first_attempt_failures`. Selection, cost basis (diesel valued by litres burnt) and the
other fields are read exactly as prepare_deck_data_latest.py does. Nothing is solved or rewritten.
Run from the repository root:  python outcome/2026-11-12_three_party/prepare_deck_data_rc42.py et|ct
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import prepare_deck_data_latest as base  # noqa: E402

SERIES = sys.argv[1]
assert SERIES in ("et", "ct"), SERIES
BASIC_WEEK_JPY = {"et": {90: 44664, 200: 99254, 400: 198508, 900: 446642}, "ct": {90: 0, 200: 0, 400: 0, 900: 0}}[SERIES]
MEM24 = {("et", 200, base.U, "bev"), ("ct", 900, base.U, "bev"), ("ct", 90, base.U, "bev")}
base.VERSION.update({"rc42": "19dc0780", "rc42m24": "19dc0780"})
base.CASES.clear()
for limit in base.LIMITS:
    for week in (base.W, base.S, base.U):
        for start, k in (("bev", "b"), ("ice", "i")):
            name = f"{SERIES}{k}{limit:03d}"
            base.CASES[(limit, week, start)] = (f"rc42m24/{name}m24/{week}" if (SERIES, limit, week, start) in MEM24
                                                else f"rc42/{name}/{week}")
base.FIRST_ATTEMPT_FAILURES[:] = [
    {"case": f"rc42/{s}{'b'}{g:03d}/{w}", "reason": "day-ahead Stage 2 memory_limit at 14 GiB; rerun once at 24 GiB"}
    for (s, g, w, _) in sorted(MEM24) if s == SERIES]
OUT = base.HERE / f"deck_data_rc42_{SERIES}.json"


def annotate(d):
    for r in d["cases"] + d["pairs"]:
        r["tariff_series"] = SERIES
        r["basic_charge_week_jpy"] = BASIC_WEEK_JPY[r["grid_limit_kw"]]
    d["tariff_series"] = SERIES


base.main(OUT, annotate)
print("wrote", OUT)
