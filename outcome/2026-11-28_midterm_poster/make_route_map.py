"""Route map of Shibu 21-23 (Tsurumaki depot) for the poster and the progress deck.

Stop positions come from the built ODPT timetable data (data/built/tokyu_full, read-only).
Consecutive stops of each route pattern are joined by straight lines, so the lines are
not the road geometry. No background map is used.

Run from the repository root:
  .venv/Scripts/python.exe outcome/2026-11-28_midterm_poster/make_route_map.py
Writes route_map_ja.png and route_map_en.png next to this script.
"""
from pathlib import Path
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).parent
BUILT = Path("data/built/tokyu_full")
FAMILIES = ["渋21", "渋22", "渋23"]
COLORS = {"渋21": "#0072B2", "渋22": "#E69F00", "渋23": "#009E73"}  # Okabe-Ito
# label, dx, dy (points), horizontal alignment
LABELS = {
    "渋谷駅": ("Shibuya Sta.", -12, 8, "right"),
    "三軒茶屋": ("Sangen-jaya", 4, -18, "left"),
    "上町": ("Kamimachi", 0, 10, "center"),
    "桜小学校": ("Sakura Elem. School", -4, 10, "right"),
    "松が丘交番前": ("Matsugaoka Koban-mae", 8, -4, "left"),
    "用賀駅": ("Yoga Sta.", 0, -16, "center"),
    "祖師ヶ谷大蔵駅": ("Soshigaya-Okura Sta.", -4, -18, "left"),
}
# English names are longer: separate offsets where the Japanese ones would collide.
EN_OFFSETS = {"上町": (0, 12, "center")}
# The two short-turn terminals are left unlabelled in English: the names do not fit next to Kamimachi.
EN_SKIP = {"桜小学校", "松が丘交番前"}
DEPOT = ("弦巻営業所", "Tsurumaki depot")

routes = pd.read_parquet(BUILT / "routes.parquet")
stops = pd.read_parquet(BUILT / "stops.parquet").drop_duplicates("id").set_index("id")
routes = routes[routes.routeFamilyCode.isin(FAMILIES)]
lat0 = 35.642
kx = 111.32 * math.cos(math.radians(lat0))  # km per degree of longitude
ky = 110.95  # km per degree of latitude


def xy(stop_id):
    row = stops.loc[stop_id]
    return (float(row.lon) - 139.65) * kx, (float(row.lat) - lat0) * ky


def draw(lang):
    ja = lang == "ja"
    plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "MS Gothic"] if ja else ["Arial"]
    fig, ax = plt.subplots(figsize=(9.0, 4.6), dpi=300)
    named = {}
    # Draw the less frequent families on top with a small offset so shared sections stay visible.
    for k, fam in enumerate(FAMILIES):
        off = (k - 1) * 0.045
        sub = routes[routes.routeFamilyCode == fam].sort_values("tripCount", ascending=False)
        for _, r in sub.iterrows():
            ids = [s for s in list(r.stopSequence) if s in stops.index]
            pts = [xy(s) for s in ids]
            ax.plot([p[0] for p in pts], [p[1] + off for p in pts], color=COLORS[fam], lw=2.4,
                    solid_capstyle="round", solid_joinstyle="round", zorder=3 + k, alpha=0.95)
            ax.scatter([p[0] for p in pts], [p[1] + off for p in pts], s=7, color="white",
                       edgecolor=COLORS[fam], linewidth=0.7, zorder=6 + k)
            for s, p in zip(ids, pts):
                named.setdefault(str(stops.loc[s, "name"]), p)
    for name, (en, dx, dy, ha) in LABELS.items():
        if name not in named:
            raise SystemExit(f"stop not found in the route patterns: {name}")
        x, y = named[name]
        if not ja and name in EN_SKIP:
            continue
        if not ja and name in EN_OFFSETS:
            dx, dy, ha = EN_OFFSETS[name]
        ax.scatter([x], [y], s=46, color="white", edgecolor="#222222", linewidth=1.2, zorder=12)
        ax.annotate(name if ja else en, (x, y), xytext=(dx, dy), textcoords="offset points", ha=ha,
                    fontsize=13, color="#222222", zorder=13,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8))
    depot = stops[stops.name == DEPOT[0]].iloc[0]
    dx_, dy_ = (float(depot.lon) - 139.65) * kx, (float(depot.lat) - lat0) * ky
    ax.scatter([dx_], [dy_], marker="*", s=330, color="#D55E00", edgecolor="white", linewidth=1.0, zorder=14)
    ax.annotate((DEPOT[0] + "\n（充電器10基・太陽光・蓄電池）") if ja else (DEPOT[1] + "\n(10 chargers, PV, battery)"),
                (dx_, dy_), xytext=(10, -44) if not ja else (10, -30), textcoords="offset points", ha="left", fontsize=13,
                color="#D55E00", fontweight="bold", zorder=15,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8))
    # legend with the weekday trip counts of the scenario week is not derivable here; show route families only
    handles = [plt.Line2D([0], [0], color=COLORS[f], lw=3) for f in FAMILIES]
    names = FAMILIES if ja else ["Shibu 21", "Shibu 22", "Shibu 23"]
    ax.legend(handles, names, loc="upper left", frameon=False, fontsize=13, ncol=3, handlelength=1.6,
              columnspacing=1.4, borderaxespad=0.2)
    ax.set_aspect("equal")
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    ax.set_xlim(x0 - 0.3, x1 + 0.5)
    ax.set_ylim(y0 - 0.55, y1 + 0.45)
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    # scale bar (1 km) and north arrow
    sx, sy = x1 - 1.45, y0 + 0.22
    ax.plot([sx, sx + 1.0], [sy, sy], color="#222222", lw=2.2, zorder=20)
    for t in (sx, sx + 1.0):
        ax.plot([t, t], [sy - 0.05, sy + 0.05], color="#222222", lw=1.4, zorder=20)
    ax.text(sx + 0.5, sy + 0.09, "1 km", ha="center", va="bottom", fontsize=12, color="#222222")
    ax.annotate("", xy=(x1 - 0.2, y1 - 0.12), xytext=(x1 - 0.2, y1 - 0.72),
                arrowprops=dict(arrowstyle="-|>", color="#222222", lw=1.6))
    ax.text(x1 - 0.2, y1 - 0.80, "N", ha="center", va="top", fontsize=11, color="#222222", fontweight="bold")
    ax.axis("off")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    out = HERE / f"route_map_{lang}.png"
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)
    print("wrote", out, "extent_km", round(x1 - x0, 1), "x", round(y1 - y0, 1))


draw("ja")
draw("en")
