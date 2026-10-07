"""Export the frozen two-day mechanism example; no solver or network access."""

import csv
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent
BLUE, INK, GRAY = "#0098D7", "#31343B", "#9BA1A8"


def main():
    source = ROOT / "outcome/2026-09-28_september_presentation/evidence/2025-05-12/energy_15min.csv"
    if hashlib.sha256(source.read_bytes()).hexdigest() != "cd69d354e4b0fe211f036ea263bafc6b93b89462806ffd6491ebf7dc693ef215":
        raise ValueError("Frozen May energy evidence changed")
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = [r for r in csv.DictReader(stream) if r["interval_start_jst"][:10] in {"2025-05-12", "2025-05-13"}]
    if len(rows) != 192:
        raise ValueError("The two-day figure requires 192 contiguous 15-minute intervals")
    stamps = [datetime.fromisoformat(r["interval_start_jst"]) for r in rows]
    if any(b - a != timedelta(minutes=15) for a, b in zip(stamps, stamps[1:])):
        raise ValueError("Noncontinuous input")
    font = FontProperties(fname="C:/Windows/Fonts/meiryo.ttc")
    plt.rcParams.update({"font.family": font.get_name(), "font.size": 11, "svg.fonttype": "none"})
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                             gridspec_kw={"height_ratios": [1, 1, 1.1]})
    fig.subplots_adjust(left=0.10, right=0.97, top=0.86, bottom=0.13, hspace=0.16)
    fig.text(0.10, 0.95, "翌朝の買電と、その後の日中の余剰PV", fontsize=19, color=INK)
    fig.text(0.10, 0.913, "2025/5/12–13　渋21〜23・保存済み実行系列（水平面GHI比例PV）", fontsize=11, color=INK)
    series = lambda k: [float(r[k]) for r in rows]
    pv = [4 * sum(float(r[k]) for k in ("pv_to_bus_kwh", "pv_to_bess_kwh", "pv_curtailed_kwh")) for r in rows]
    axes[0].step(stamps, pv, where="post", color=BLUE, label="PV供給可能量")
    axes[0].fill_between(stamps, [4*x for x in series("pv_curtailed_kwh")], step="post",
                         color=GRAY, alpha=0.4, label="PV抑制")
    axes[0].set_ylabel("PV電力 [kW]")
    axes[1].step(stamps, [4*x for x in series("grid_import_kwh")], where="post", color=BLUE, label="買電")
    axes[1].step(stamps, [4*x for x in series("bus_charge_kwh")], where="post", color=INK,
                 linestyle="--", linewidth=1, label="バス充電供給量")
    axes[1].axhline(200, color=GRAY, linestyle=":", linewidth=1.2, label="超過モデル費の閾値200 kW")
    axes[1].set_ylabel("充電・買電 [kW]")
    end_stamps = [t + timedelta(minutes=15) for t in stamps]
    axes[2].plot(end_stamps, series("bess_soc_end_kwh"), color=BLUE, label="BESS残量（区間末）")
    axes[2].axhline(1200, color=GRAY, linestyle=":", linewidth=1.2, label="運用下限1,200 kWh")
    axes[2].set_ylabel("BESS残量 [kWh]")
    axes[2].set_ylim(0, 5100)
    start, end = datetime(2025, 5, 12), datetime(2025, 5, 14)
    for ax in axes:
        ax.set_xlim(start, end)
        ax.set_ylim(bottom=0)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="#E8EAED", linewidth=0.6)
        ax.axvline(datetime(2025, 5, 13), color=GRAY, linestyle=(0, (3, 4)), linewidth=0.7)
        ax.axvspan(datetime(2025, 5, 13), datetime(2025, 5, 13, 6), color="#F0F1F3", zorder=-1)
        ax.legend(loc="upper left", frameon=False, fontsize=9, ncol=3)
        ax.tick_params(axis="x", length=0)
    axes[2].set_xticks([start + timedelta(hours=12), start + timedelta(days=1, hours=12)])
    axes[2].set_xticklabels(["5/12（月）", "5/13（火）"], fontsize=12)
    axes[0].set_ylim(0, 1150)
    axes[0].text(datetime(2025, 5, 12, 8), 950, "当日PV積算 1,797 kWh", fontsize=10, color=INK)
    axes[0].text(datetime(2025, 5, 13, 8), 950, "当日PV積算 6,333 kWh\nうち抑制 2,431 kWh", fontsize=10, color=INK)
    fig.text(0.10, 0.072, "5/13 00–06時の買電は2,243 kWh。200 kW×6時間＝1,200 kWhを上回る。", fontsize=10, color=INK)
    fig.text(0.10, 0.042, "出典：固定版f524eca2の実行CSV。後日の余剰は前夜へ移せない。充電分散の可否・最適性は未検証。", fontsize=9, color=INK)
    for suffix in ("png", "svg"):
        fig.savefig(OUTPUT / f"may_time_mismatch.{suffix}", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
