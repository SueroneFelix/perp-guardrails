"""Render the three figures used in ARTICLE.md from results/*.csv.

Requires matplotlib (optional dependency, see requirements-figures.txt).
    python figures.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
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
    fig.savefig(path.with_suffix(".svg"), metadata={"Date": None})
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
    fig.savefig(path.with_suffix(".svg"), metadata={"Date": None})
    plt.close(fig)
    return path


def fig_dedupe(df: pd.DataFrame, per_symbol: pd.DataFrame) -> Path:
    order = ["dup_nodedupe", "dup_dedupe"]
    d = df[df["group"] == "dup"].set_index("config").loc[order]
    worst = (
        per_symbol[per_symbol["group"] == "dup"]
        .groupby("config")["max_gross_leverage"]
        .max()
        .loc[order]
    )
    mean = d["max_gross_leverage"]
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.3))

    labels = ["no dedupe", "with dedupe"]
    colors = [COLORS[c] for c in d.index]

    bars = axes[0].bar(
        labels, mean, color=colors, width=0.45,
        yerr=[np.zeros(len(mean)), (worst - mean).clip(lower=0)],
        capsize=4, ecolor=INK, error_kw={"linewidth": 1.1},
    )
    for bar, m, w in zip(bars, mean, worst):
        axes[0].text(
            bar.get_x() + bar.get_width() / 2, w + 0.3,
            f"mean {m:.1f}x\nworst {w:.1f}x",
            ha="center", va="bottom", fontsize=8.5, color=INK, linespacing=1.25,
        )
    axes[0].set_ylim(0, 13.5)
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
    fig.savefig(path.with_suffix(".svg"), metadata={"Date": None})
    plt.close(fig)
    return path


def fig_leverage(df: pd.DataFrame, per_symbol: pd.DataFrame) -> Path:
    caps = [5, 3, 2, 1]
    names = ["control", "cap_3x", "cap_2x", "cap_1x"]
    d = df.set_index("config").loc[names]
    fin = per_symbol[per_symbol["config"].isin(names)]
    keep_half, keep_all = [], []
    for name in names:
        equity = fin.loc[fin["config"] == name, "final_equity"]
        keep_half.append((equity >= 5_000).mean() * 100)
        keep_all.append((equity >= 10_000).mean() * 100)

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.4), gridspec_kw={"width_ratios": [1, 1.15]})
    labels = [f"{c}x" for c in caps]

    bars = axes[0].bar(labels, (d["ruin_rate"] * 100).tolist(), color="#c0392b", width=0.55)
    for bar, rate in zip(bars, d["ruin_rate"]):
        axes[0].text(
            bar.get_x() + bar.get_width() / 2, rate * 100 + 2,
            f"{rate * 100:.0f}%\n{int(round(rate * 50))}/50",
            ha="center", va="bottom", fontsize=8.5, color=INK, linespacing=1.2,
        )
    axes[0].set_ylim(0, 98)
    axes[0].set_ylabel("accounts that hit zero equity (%)")
    axes[0].set_xlabel("leverage cap")
    axes[0].set_title("Ruin falls at every step - never to zero", loc="left", fontsize=10)
    _clean(axes[0])

    width = 0.38
    x = np.arange(len(caps))
    axes[1].bar(x - width / 2, keep_half, width, label="kept half the capital", color="#2d6cdf")
    axes[1].bar(x + width / 2, keep_all, width, label="ended above break-even", color="#1e8449")
    for i, (half, all_) in enumerate(zip(keep_half, keep_all)):
        if half or all_:
            axes[1].text(i - width / 2, half + 0.6, f"{half:.0f}%", ha="center", fontsize=8.5, color="#2d6cdf")
            axes[1].text(i + width / 2, all_ + 0.6, f"{all_:.0f}%", ha="center", fontsize=8.5, color="#1e8449")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels)
    axes[1].set_ylim(0, 20)
    axes[1].set_ylabel("share of the 50 accounts (%)")
    axes[1].set_xlabel("leverage cap")
    axes[1].legend(frameon=False, fontsize=8, loc="upper left")
    axes[1].set_title("...but surviving is not the same as keeping money", loc="left", fontsize=10)
    _clean(axes[1])

    fig.suptitle(
        "Leverage cap sweep, same 50 accounts, 2022-2025",
        x=0.012, ha="left", fontsize=11, color=INK,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    path = OUT / "fig4_leverage.png"
    fig.savefig(path, dpi=200)
    fig.savefig(path.with_suffix(".svg"), metadata={"Date": None})
    plt.close(fig)
    return path


def fig_dup_rate(per_symbol: pd.DataFrame) -> Path:
    order = ["dup_0pct", "dup_1pct", "dup_5pct", "dup_nodedupe", "dup_20pct"]
    rates = [0, 1, 5, 10, 20]
    stats = []
    for name in order:
        rows = per_symbol[per_symbol["config"] == name]
        stats.append((
            rows["max_gross_leverage"].mean(),
            rows["max_gross_leverage"].max(),
            rows["ruined"].mean() * 100,
        ))
    mean_peak, worst_peak, ruin = zip(*stats)

    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.5))
    labels = [f"{rate}%" for rate in rates]

    bars = axes[0].bar(labels, mean_peak, color="#2d6cdf", width=0.55, label="mean peak exposure")
    axes[0].plot(labels, worst_peak, linestyle="none", marker="_", markersize=13,
                 markeredgewidth=2.2, color="#c0392b", label="worst account")
    for bar, mean, worst in zip(bars, mean_peak, worst_peak):
        label = f"{mean:.1f}x" if worst - mean < 0.2 else f"{mean:.1f}x mean"
        axes[0].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.25,
                     label, ha="center", fontsize=8.5, color="#2d6cdf")
        if worst - mean >= 0.2:
            axes[0].text(bar.get_x() + bar.get_width() / 2, worst + 0.35,
                         f"{worst:.1f}x", ha="center", fontsize=8.5, color="#c0392b")
    axes[0].axhline(1.0, color=INK, linewidth=0.9, linestyle=":")
    axes[0].set_ylim(0, 17)
    axes[0].set_ylabel("peak gross exposure (x equity)")
    axes[0].set_xlabel("share of orders re-sent")
    axes[0].set_title("The 1x claim breaks at 1%", loc="left", fontsize=10)
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    _clean(axes[0])

    bars = axes[1].bar(labels, ruin, color="#c0392b", width=0.55)
    for bar, value in zip(bars, ruin):
        axes[1].text(bar.get_x() + bar.get_width() / 2, value + 1.2, f"{value:.0f}%",
                     ha="center", fontsize=8.5, color=INK)
    axes[1].axhline(ruin[0], color=INK, linewidth=0.9, linestyle="--")
    axes[1].annotate(
        "no duplicates", (4.35, ruin[0] - 4), fontsize=8, color=INK, ha="right",
    )
    axes[1].set_ylim(0, 55)
    axes[1].set_ylabel("accounts that hit zero equity (%)")
    axes[1].set_xlabel("share of orders re-sent")
    axes[1].set_title("The account breaks at 10%", loc="left", fontsize=10)
    _clean(axes[1])

    fig.suptitle(
        "Duplicate-order rate, 50 accounts at 1x, 2022-2025",
        x=0.012, ha="left", fontsize=11, color=INK,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    path = OUT / "fig5_dup_rate.png"
    fig.savefig(path, dpi=200)
    fig.savefig(path.with_suffix(".svg"), metadata={"Date": None})
    plt.close(fig)
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(RESULTS / "summary_overall.csv")
    per_symbol = pd.read_csv(RESULTS / "per_symbol.csv")
    written = [fig_survival(df), fig_tail(df), fig_dedupe(df, per_symbol)]

    lev_dir = RESULTS / "leverage"
    if (lev_dir / "summary_overall.csv").exists():
        written.append(
            fig_leverage(
                pd.read_csv(lev_dir / "summary_overall.csv"),
                pd.read_csv(lev_dir / "per_symbol.csv"),
            )
        )
    for path in written:
        print(f"wrote {path.relative_to(ROOT)}")

    dup_dir = RESULTS / "dup_rate"
    if (dup_dir / "per_symbol.csv").exists():
        path = fig_dup_rate(pd.read_csv(dup_dir / "per_symbol.csv"))
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
