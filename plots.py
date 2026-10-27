"""
Графіки для статті (PNG, 300 dpi).

  python plots.py              # читає results/, зберігає results/figures/

Рисунки:
  fig1_classes.png     - розподіл тестів за класами в раундах 1-2
  fig2_per_function.png- тести, що закріплюють дефект, для кожної функції: контрольна vs експериментальна
  fig3_rounds.png      - частка тестів, що закріплюють дефект, і мутаційна оцінка за раундами
  fig4_bug_types.png   - тести, що закріплюють дефект, за типом дефекту (раунди 1-2)
"""
import argparse
import json
import os
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

CLASSES = ("detects", "locks", "neutral", "broken")
CLASS_EN = {"detects": "Detects\nthe defect", "locks": "Locks in\nthe defect",
            "neutral": "Neutral", "broken": "Broken"}
COND_EN = {"plain": "Control (generic request)", "mutation": "Experimental (mutation feedback)"}

# дві категорії: синій і помаранчевий (перевірено на розрізнюваність при дальтонізмі);
# експериментальна умова додатково заштрихована - для чорно-білого друку
COLOR = {"plain": "#2a78d6", "mutation": "#eb6834"}
HATCH = {"plain": "", "mutation": "///"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def setup_style():
    names = {f.name for f in font_manager.fontManager.ttflist}
    family = "Times New Roman" if "Times New Roman" in names else "DejaVu Serif"
    plt.rcParams.update({
        "font.family": family, "font.size": 10.5, "axes.titlesize": 11,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "legend.frameon": False, "hatch.color": "white", "hatch.linewidth": 0.8,
        "savefig.dpi": 300, "savefig.bbox": "tight", "figure.dpi": 100,
    })


def read_jsonl(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def fig_classes(tests, out):
    fb = [t for t in tests if t["round"] >= 1]
    fig, ax = plt.subplots(figsize=(6.3, 3.4))
    w = 0.38
    for k, cond in enumerate(("plain", "mutation")):
        cnt = Counter(t["cls"] for t in fb if t["condition"] == cond)
        total = sum(cnt.values())
        vals = [100 * cnt[c] / total for c in CLASSES]
        xs = [i + (k - 0.5) * (w + 0.02) for i in range(len(CLASSES))]
        ax.bar(xs, vals, w, color=COLOR[cond], hatch=HATCH[cond], edgecolor="white",
               linewidth=0, label=f"{COND_EN[cond]}, n = {total}")
        for x, v, c in zip(xs, vals, CLASSES):
            ax.text(x, v + 0.8, f"{v:.1f}", ha="center", va="bottom",
                    fontsize=9, color=INK)
    ax.set_xticks(range(len(CLASSES)), [CLASS_EN[c] for c in CLASSES])
    ax.set_ylabel("Share of tests, %")
    ax.set_ylim(0, 45)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, fontsize=9.5)
    fig.savefig(os.path.join(out, "fig1_classes.png"))
    plt.close(fig)


def fig_rounds(tests, rounds, out):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.3, 3.0))
    for cond in ("plain", "mutation"):
        share, score = [], []
        for r in range(3):
            cnt = Counter(t["cls"] for t in tests if t["condition"] == cond and t["round"] == r)
            share.append(100 * cnt["locks"] / sum(cnt.values()))
            s = [x["mutation_score"] for x in rounds
                 if x["condition"] == cond and x["round"] == r and x["mutation_score"] is not None]
            score.append(sum(s) / len(s))
        style = dict(color=COLOR[cond], lw=2, marker="o" if cond == "plain" else "s", ms=6,
                     label=COND_EN[cond])
        a1.plot(range(3), share, **style)
        a2.plot(range(3), score, **style)
    a1.set_title("(a) Defect-locking tests", loc="left")
    a1.set_ylabel("Share of tests, %")
    a1.set_ylim(0, 45)
    a2.set_title("(b) Mutation score of the suite", loc="left")
    a2.set_ylabel("Mean over functions")
    a2.set_ylim(0.5, 0.9)
    for a in (a1, a2):
        a.set_xticks(range(3), ["0", "1", "2"])
        a.set_xlabel("Round")
        a.grid(axis="x", visible=False)
    h, l = a1.get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.08), fontsize=9.5)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig3_rounds.png"))
    plt.close(fig)


def fig_per_function(tests, rounds, out):
    keys = sorted({(r["task_id"], r["repeat"]) for r in rounds})
    cnt = {k: {"plain": 0, "mutation": 0} for k in keys}
    for t in tests:
        if t["round"] >= 1 and t["cls"] == "locks":
            cnt[(t["task_id"], t["repeat"])][t["condition"]] += 1
    pts = Counter((v["plain"], v["mutation"]) for v in cnt.values())
    m = max(max(p) for p in pts) + 1
    fig, ax = plt.subplots(figsize=(4.2, 4.0))
    ax.plot([-0.5, m], [-0.5, m], color=MUTED, lw=1, ls="--", zorder=1)
    for (x, y), n in pts.items():
        ax.scatter(x, y, s=45 + 55 * (n - 1), color=COLOR["mutation"] if y > x else
                   (COLOR["plain"] if x > y else MUTED), edgecolor="white", linewidth=1.5, zorder=3)
        if n > 1:
            ax.text(x, y, str(n), ha="center", va="center", fontsize=8, color="white",
                    fontweight="bold", zorder=4)
    above = sum(1 for v in cnt.values() if v["mutation"] > v["plain"])
    below = sum(1 for v in cnt.values() if v["mutation"] < v["plain"])
    equal = len(cnt) - above - below
    ax.text(0.5, -0.2, f"Above the diagonal (more in experimental): {above}\n"
            f"below (more in control): {below}; on the diagonal: {equal}",
            transform=ax.transAxes, ha="center", va="top", fontsize=9, color=INK)
    ax.set_xlim(-0.6, m)
    ax.set_ylim(-0.6, m)
    ax.set_xticks(range(0, m + 1, 2))
    ax.set_yticks(range(0, m + 1, 2))
    ax.set_xlabel("Control condition, tests")
    ax.set_ylabel("Experimental condition, tests")
    ax.set_aspect("equal")
    fig.savefig(os.path.join(out, "fig2_per_function.png"))
    plt.close(fig)


def fig_bug_types(tests, out):
    fb = [t for t in tests if t["round"] >= 1 and t["cls"] == "locks"]
    bugs = sorted({t["bug_type"] for t in tests},
                  key=lambda b: (-sum(1 for t in fb if t["bug_type"] == b), b))
    fig, ax = plt.subplots(figsize=(6.3, 3.3))
    h = 0.38
    for k, cond in enumerate(("plain", "mutation")):
        vals = [sum(1 for t in fb if t["bug_type"] == b and t["condition"] == cond) for b in bugs]
        ys = [i + (k - 0.5) * (h + 0.02) for i in range(len(bugs))]
        ax.barh(ys, vals, h, color=COLOR[cond], hatch=HATCH[cond], edgecolor="white",
                linewidth=0, label=COND_EN[cond])
        for y, v in zip(ys, vals):
            ax.text(v + 0.3, y, str(v), va="center", fontsize=9, color=INK)
    ax.set_yticks(range(len(bugs)), [b.capitalize() for b in bugs])
    ax.invert_yaxis()
    ax.set_xlabel("Defect-locking tests, rounds 1–2")
    ax.set_xlim(0, max(1, ax.get_xlim()[1]) + 1)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower center", bbox_to_anchor=(0.4, 1.0), ncol=2, fontsize=9.5)
    fig.savefig(os.path.join(out, "fig4_bug_types.png"))
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Figures for the article")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    tests = read_jsonl(os.path.join(args.out, "tests.jsonl"))
    rounds = read_jsonl(os.path.join(args.out, "rounds.jsonl"))
    fig_dir = os.path.join(args.out, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    setup_style()
    fig_classes(tests, fig_dir)
    fig_rounds(tests, rounds, fig_dir)
    fig_per_function(tests, rounds, fig_dir)
    fig_bug_types(tests, fig_dir)
    print(f"Figures saved to {fig_dir}")


if __name__ == "__main__":
    main()