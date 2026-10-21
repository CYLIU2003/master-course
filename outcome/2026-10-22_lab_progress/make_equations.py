"""Render the formulation summary for the lab talk as PNG images (matplotlib mathtext).

The equations are a simplified statement of the model in docs/constant/formulation.md and
src/optimization/milp/solver_adapter.py (grid limit with a non-negative excess slack, peak W >= g_t/dt).
Writes eq/<name>.png and eq/sizes.json (width/height in inches at the rendered font size).
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

EQUATIONS = {
    "objective": r"$\min\ \sum_{k,d}\, c^{\mathrm{veh}} u_{kd} + \sum_{t}\,(p^{\mathrm{e}} g_t + \pi\, s_t)"
                 r" + c^{\mathrm{f}} \sum_{j} f_j + c^{\mathrm{CO_2}} Q^{\mathrm{CO_2}}$",
    "cover": r"$\sum_{k}\ \sum_{i:(i,j)\in\mathcal{A}} x^{k}_{ij} = 1 \quad \forall j$",
    "connect": r"$(i,j)\in\mathcal{A}\ \Leftrightarrow\ t^{\mathrm{arr}}_i + t^{\mathrm{turn}}_i + t^{\mathrm{dh}}_{ij} \leq t^{\mathrm{dep}}_j$",
    "soc": r"$E_{k,t+1} = E_{k,t} + \eta\, z_{k,t}\, \Delta t - e_{k,t},\quad E^{\min}_k \leq E_{k,t} \leq E^{\max}_k$",
    "charger": r"$\sum_{k}\, \xi_{k,t} \leq N^{\mathrm{ch}} \quad \forall t$",
    "balance": r"$\sum_{k} z_{k,t}\, \Delta t = g^{\mathrm{bus}}_t + pv^{\mathrm{bus}}_t + b^{\mathrm{bus}}_t \quad \forall t$",
    "limit": r"$g_t \leq P^{\mathrm{lim}} \Delta t + s_t,\quad s_t \geq 0 \quad \forall t$",
    "peak": r"$W \geq g_t / \Delta t \quad \forall t$",
}
FONT_PT = 22


def main() -> None:
    out = Path(__file__).with_name("eq")
    out.mkdir(exist_ok=True)
    sizes = {}
    plt.rcParams["mathtext.fontset"] = "cm"
    for name, tex in EQUATIONS.items():
        fig = plt.figure(figsize=(12, 2))
        fig.text(0.01, 0.5, tex, fontsize=FONT_PT, color="#222222", va="center")
        target = out / f"{name}.png"
        fig.savefig(target, dpi=300, transparent=True, bbox_inches="tight", pad_inches=0.04)
        plt.close(fig)
        img = plt.imread(target)
        sizes[name] = {"w": round(img.shape[1] / 300, 3), "h": round(img.shape[0] / 300, 3)}
    (out / "sizes.json").write_text(json.dumps(sizes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(sizes))


if __name__ == "__main__":
    main()
