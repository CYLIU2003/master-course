"""Route map of Shibu 21-23 (Tsurumaki depot) for the poster and the progress deck.

Stop positions come from the built ODPT timetable data (data/built/tokyu_full, read-only).
Consecutive stops of each route pattern are joined by straight lines, so the lines are
not the road geometry. Background: OpenStreetMap tiles stitched by fetch_osm_basemap.py
(osm_basemap_z15.png), lightened; the figure carries the "(c) OpenStreetMap contributors" credit.

Run from the repository root:
  .venv/Scripts/python.exe outcome/2026-11-28_midterm_poster/make_route_map.py
Writes route_map_{ja,en}.png (slide) and route_map_{ja,en}_poster.png (larger type).
"""
from pathlib import Path
import json
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

HERE = Path(__file__).parent
BUILT = Path("data/built/tokyu_full")
FAMILIES = ["渋21", "渋22", "渋23"]
COLORS = {"渋21": "#0072B2", "渋22": "#D55E00", "渋23": "#009E73"}  # Okabe-Ito, dark enough on the map
# English label, dx, dy (in type-size units), horizontal alignment
LABELS = {
    "渋谷駅": ("Shibuya Sta.", -0.9, 0.7, "right"),
    "三軒茶屋": ("Sangen-jaya", 0.3, -1.5, "left"),
    "上町": ("Kamimachi", 0.0, 0.9, "center"),
    "桜小学校": ("Sakura Elem. School", -0.4, 0.9, "right"),
    "松が丘交番前": ("Matsugaoka Koban-mae", 0.7, -0.3, "left"),
    "用賀駅": ("Yoga Sta.", 0.0, -1.5, "center"),
    "祖師ヶ谷大蔵駅": ("Soshigaya-Okura Sta.", -0.3, -1.5, "left"),
}
# The two short-turn terminals are left unlabelled in English: the names do not fit next to Kamimachi.
EN_SKIP = {"桜小学校", "松が丘交番前"}
DEPOT = ("弦巻営業所", "Tsurumaki depot")

meta = json.loads((HERE / "osm_basemap_z15.json").read_text(encoding="utf-8"))
Z, TX0, TY0 = meta["zoom"], meta["tx0"], meta["ty0"]
base = np.asarray(Image.open(HERE / "osm_basemap_z15.png").convert("RGB"), dtype=float) / 255.0
grey = base.mean(axis=2, keepdims=True)
base = 0.45 * (0.35 * base + 0.65 * grey) + 0.55  # desaturate and lighten so the routes stand out

routes = pd.read_parquet(BUILT / "routes.parquet")
stops = pd.read_parquet(BUILT / "stops.parquet").drop_duplicates("id").set_index("id")
routes = routes[routes.routeFamilyCode.isin(FAMILIES)]


def xy(lon, lat):
    """Web-Mercator pixel position inside the stitched image (y grows downwards)."""
    n = 2 ** Z
    return (((lon + 180) / 360 * n) - TX0) * 256, (((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n) - TY0) * 256


def stop_xy(stop_id):
    row = stops.loc[stop_id]
    return xy(float(row.lon), float(row.lat))


LAT0 = 35.642
PX_PER_KM = 1000.0 / (156543.03392 * math.cos(math.radians(LAT0)) / 2 ** Z)


def draw(lang, suffix, fs):
    ja = lang == "ja"
    plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "MS Gothic"] if ja else ["Arial"]
    pts_all = [stop_xy(s) for seq in routes.stopSequence for s in seq if s in stops.index]
    xs, ys = [p[0] for p in pts_all], [p[1] for p in pts_all]
    x0, x1 = min(xs) - 0.45 * PX_PER_KM, max(xs) + 0.6 * PX_PER_KM
    y0, y1 = min(ys) - 0.75 * PX_PER_KM, max(ys) + 0.5 * PX_PER_KM
    width_in = 9.0
    fig = plt.figure(figsize=(width_in, width_in * (y1 - y0) / (x1 - x0)), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(base, extent=(0, base.shape[1], base.shape[0], 0), interpolation="lanczos", zorder=1)
    named = {}
    lw = 2.6
    for k, fam in enumerate(FAMILIES):
        off = (k - 1) * 0.05 * PX_PER_KM  # small offset so shared sections stay visible
        sub = routes[routes.routeFamilyCode == fam].sort_values("tripCount", ascending=False)
        for _, r in sub.iterrows():
            ids = [s for s in list(r.stopSequence) if s in stops.index]
            pts = [stop_xy(s) for s in ids]
            px, py = [p[0] for p in pts], [p[1] - off for p in pts]
            ax.plot(px, py, color="white", lw=lw + 1.6, solid_capstyle="round", solid_joinstyle="round", zorder=3 + k)
            ax.plot(px, py, color=COLORS[fam], lw=lw, solid_capstyle="round", solid_joinstyle="round", zorder=3 + k)
            ax.scatter(px, py, s=7, color="white", edgecolor=COLORS[fam], linewidth=0.7, zorder=8 + k)
            for s, p in zip(ids, pts):
                named.setdefault(str(stops.loc[s, "name"]), p)
    box = dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.88)
    for name, (en, dx, dy, ha) in LABELS.items():
        if name not in named:
            raise SystemExit(f"stop not found in the route patterns: {name}")
        if not ja and name in EN_SKIP:
            continue
        x, y = named[name]
        ax.scatter([x], [y], s=50, color="white", edgecolor="#222222", linewidth=1.3, zorder=14)
        ax.annotate(name if ja else en, (x, y), xytext=(dx * fs, dy * fs), textcoords="offset points", ha=ha,
                    fontsize=fs, color="#222222", zorder=15, bbox=box)
    depot = stops[stops.name == DEPOT[0]].iloc[0]
    dx_, dy_ = xy(float(depot.lon), float(depot.lat))
    ax.scatter([dx_], [dy_], marker="*", s=420, color="#CC0000", edgecolor="white", linewidth=1.2, zorder=16)
    if suffix:  # poster: the map replaces the equipment diagram, so the depot label carries the fleet and equipment
        depot_text = ((DEPOT[0] + "\n電気バス35台・燃料バス25台\n充電器90 kW×10\n太陽光1,000 kW・蓄電池6,000 kWh") if ja else
                      (DEPOT[1] + "\n35 electric + 25 diesel buses\n10 chargers (90 kW)\nPV 1,000 kW, battery 6,000 kWh"))
    else:
        depot_text = (DEPOT[0] + "\n（充電器10基・太陽光・蓄電池）") if ja else (DEPOT[1] + "\n(10 chargers, PV, battery)")
    ax.annotate(depot_text,
                (dx_, dy_), xytext=(0.9 * fs, (-6.6 if suffix else -3.4) * fs), textcoords="offset points", ha="left", fontsize=fs,
                color="#CC0000", fontweight="bold", zorder=17, bbox=box)
    handles = [plt.Line2D([0], [0], color=COLORS[f], lw=3.2) for f in FAMILIES]
    names = FAMILIES if ja else ["Shibu 21", "Shibu 22", "Shibu 23"]
    legend = ax.legend(handles, names, loc="upper left", frameon=True, fontsize=fs, ncol=3, handlelength=1.5,
                       columnspacing=1.2, borderaxespad=0.5, framealpha=0.9, edgecolor="none")
    legend.set_zorder(20)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    # scale bar (1 km) and north arrow, on white patches
    # top, right of the legend: the lower right holds the depot label on the poster
    sx, sy = x0 + 0.63 * (x1 - x0), y0 + 0.46 * PX_PER_KM
    ax.add_patch(plt.Rectangle((sx - 0.12 * PX_PER_KM, sy - 0.36 * PX_PER_KM), 1.24 * PX_PER_KM, 0.5 * PX_PER_KM,
                               fc="white", ec="none", alpha=0.88, zorder=18))
    ax.plot([sx, sx + PX_PER_KM], [sy, sy], color="#222222", lw=2.2, zorder=20)
    for t in (sx, sx + PX_PER_KM):
        ax.plot([t, t], [sy - 0.05 * PX_PER_KM, sy + 0.05 * PX_PER_KM], color="#222222", lw=1.4, zorder=20)
    ax.text(sx + 0.5 * PX_PER_KM, sy - 0.08 * PX_PER_KM, "1 km", ha="center", va="bottom", fontsize=fs * 0.9, color="#222222", zorder=20)
    nx = x1 - 0.22 * PX_PER_KM
    ax.add_patch(plt.Rectangle((nx - 0.16 * PX_PER_KM, y0 + 0.06 * PX_PER_KM), 0.32 * PX_PER_KM, 0.95 * PX_PER_KM,
                               fc="white", ec="none", alpha=0.88, zorder=18))
    ax.annotate("", xy=(nx, y0 + 0.12 * PX_PER_KM), xytext=(nx, y0 + 0.66 * PX_PER_KM),
                arrowprops=dict(arrowstyle="-|>", color="#222222", lw=1.6), zorder=20)
    ax.text(nx, y0 + 0.70 * PX_PER_KM, "N", ha="center", va="top", fontsize=fs * 0.95, color="#222222", fontweight="bold", zorder=20)
    ax.text(x0 + 0.06 * PX_PER_KM, y1 - 0.05 * PX_PER_KM, "© OpenStreetMap contributors", ha="left", va="bottom",
            fontsize=fs * 0.62, color="#444444", zorder=20, bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.85))
    ax.axis("off")
    out = HERE / f"route_map_{lang}{suffix}.png"
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)
    print("wrote", out.name, "extent_km", round((x1 - x0) / PX_PER_KM, 1), "x", round((y1 - y0) / PX_PER_KM, 1),
          "aspect", round((y1 - y0) / (x1 - x0), 4))


for lang in ("ja", "en"):
    draw(lang, "", 13)
    draw(lang, "_poster", 17)
