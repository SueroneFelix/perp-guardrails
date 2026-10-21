"""Render the three figures used in ARTICLE.md from results/*.csv.

Requires matplotlib (optional dependency, see requirements-figures.txt).
    python figures.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT = RESULTS / "figures"

INK = "#1b1b1b"
MUTED = "#6b7280"
GRID = "#e5e7eb"
COLORS = {
    "control": "#c0392b",
    "kill_5pct": "#d68910",
    "cap_1x": "#2d6cdf",
    "all": "#1e8449",
    "dup_nodedupe": "#c0392b",
    "dup_dedupe": "#1e8449",
}
LABELS = {
    "control": "No guardrails (5x)",
    "kill_5pct": "Daily kill switch only (5x)",
    "cap_1x": "Exposure cap only (1x)",
    "all": "Cap + kill switch",
    "dup_nodedupe": "Replays executed",
    "dup_dedupe": "Replays deduplicated",
}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.edgecolor": GRID,
    "axes.labelcolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.titlecolor": INK,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
})


def _clean(ax, axis: str = "y") -> None:
    ax.spines[["top", "right", "left" if axis == "y" else "bottom"]].set_visible(False)
    ax.grid(axis=axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def fig_survival(df: pd.DataFrame) -> Path:
    order = ["control", "kill_5pct", "cap_1x", "all"]
    d = df.set_index("config").loc[order]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    bars = ax.barh(
        [LABELS[c] for c in order],
        d["ruin_rate"] * 100,
        color=[COLORS[c] for c in order],
        height=0.55,
    )
    for bar, rate, n in zip(bars, d["ruin_rate"], d["n"]):
        ax.text(
            bar.get_width() + 1.2,
            bar.get_y() + bar.get_height() / 2,
            f"{rate * 100:.0f}%  ({int(round(rate * n))}/{int(n)})",
            va="center",
            fontsize=9.5,
            color=INK,
        )
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of the 50 strategy x market combinations that hit zero equity")
    ax.invert_yaxis()
    _clean(ax, "x")
    ax.set_title("Same five strategies, same four years. Only the guardrails differ.", loc="left", fontsize=11, pad=10)
    fig.tight_layout()
    path = OUT / "fig1_ruin_rate.png"
    fig.savefig(path, dpi=200)
    fig.savefig(path.with_suffix(".svg"))
    plt.close(fig)
    return path


def fig_tail(df: pd.DataFrame) -> Path:
    d = df[df["group"] == "main"]
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    text_at = {
        "control": (-96.0, -66.0),
        "kill_5pct": (-96.0, -21.5),
        "cap_1x": (-76.0, -13.8),
        "all": (-70.0, -3.2),
    }
    for _, row in d.iterrows():
        ax.scatter(
            row["total_return"] * 100,
            row["cvar_5pct"] * 100,
            s=170,
            color=COLORS[row["config"]],
            edgecolor="white",
            linewidth=1.6,
            zorder=3,
        )
        ax.annotate(
            LABELS[row["config"]],
            (row["total_return"] * 100, row["cvar_5pct"] * 100),
            xytext=text_at[row["config"]],
            fontsize=9,
            color=INK,
            ha="left",
        )
    ax.axhline(0, color=GRID, linewidth=1)
    ax.set_xlim(-108, 16)
    ax.set_ylim(-72, 6)
    ax.set_xlabel("mean total return over 2022-2025 (%)")
    ax.set_ylabel("daily CVaR(5%) — average of the worst 5% of days (%)")
    _clean(ax, "both")
    ax.set_title("Guardrails do not make a bad strategy good. They move the tail.", loc="left", fontsize=11, pad=10)
    fig.tight_layout()
    path = OUT / "fig2_tail.png"
    fig.savefig(path, dpi=200)
    fig.savefig(path.with_suffix(".svg"))
    plt.close(fig)
    return path


def fig_dedupe(df: pd.DataFrame) -> Path:
    d = df[df["group"] == "dup"].set_index("config").loc[["dup_nodedupe", "dup_dedupe"]]
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.1))

    labels = ["no dedupe", "with dedupe"]
    colors = [COLORS[c] for c in d.index]

    bars = axes[0].bar(labels, d["max_gross_leverage"], color=colors, width=0.5)
    for bar, v in zip(bars, d["max_gross_leverage"]):
        axes[0].text(bar.get_x() + bar.get_width() / 2, v + 0.08, f"{v:.1f}x", ha="center", fontsize=9.5, color=INK)
    axes[0].set_ylim(0, 4.6)
    axes[0].set_ylabel("peak gross exposure (x equity)")
    axes[0].set_title("What 10% duplicate orders do to size", loc="left", fontsize=10)
    _clean(axes[0])

    bars = axes[1].bar(labels, d["ruin_rate"] * 100, color=colors, width=0.5)
    for bar, v in zip(bars, d["ruin_rate"] * 100):
        axes[1].text(bar.get_x() + bar.get_width() / 2, v + 1.0, f"{v:.0f}%", ha="center", fontsize=9.5, color=INK)
    axes[1].set_ylim(0, 42)
    axes[1].set_ylabel("ruin rate (%)")
    axes[1].set_title("...and to survival", loc="left", fontsize=10)
    _clean(axes[1])

    for ax in axes:
        ax.tick_params(axis="x", labelsize=8.5)
    fig.tight_layout()
    path = OUT / "fig3_dedupe.png"
    fig.savefig(path, dpi=200)
    fig.savefig(path.with_suffix(".svg"))
    plt.close(fig)
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(RESULTS / "summary_overall.csv")
    for path in (fig_survival(df), fig_tail(df), fig_dedupe(df)):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
