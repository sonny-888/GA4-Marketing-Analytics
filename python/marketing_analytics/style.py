"""Matplotlib style shared by every Python chart, built from design/tokens.json (same tokens as r/R/style.R,
the Power BI theme, the report and the deck).

Usage:
    from marketing_analytics.style import PAL, apply, finish
    apply()
    fig, ax = plt.subplots()
    ...
    finish(fig, ax, "Title that states the finding", "What is measured", "figures/chart.png")
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager

TOKENS = json.loads((Path(__file__).resolve().parents[2] / "design" / "tokens.json").read_text(encoding="utf-8"))
_C = TOKENS["color"]
PAL = {
    "primary": _C["data.primary"], "primary_strong": _C["data.primary.strong"], "secondary": _C["data.secondary"],
    "context": _C["data.comparison"],
    # blue carries the data; "accent" (aurora red) marks the one thing to look at against grey context
    "accent": _C["data.highlight"], "accent_text": _C["data.highlight.text"],
    "positive": _C["status.positive"], "negative": _C["status.negative"],
    "ink": _C["text.primary"], "ink_2": _C["text.secondary"], "muted": _C["text.muted"],
    "border": _C["border.subtle"], "surface": _C["background.primary"],
    "categorical": _C["categorical"],
}
SOURCE = "Source: GA4 public sample, Google Merchandise Store, 1 Nov 2020 to 31 Jan 2021."


def _installed(families: list[str]) -> list[str]:
    """Keep only fonts this machine has, so matplotlib doesn't warn about every missing fallback."""
    available = {f.name for f in font_manager.fontManager.ttflist}
    return [f for f in families if f in available]


def apply() -> None:
    plt.rcParams.update({
        "font.family": _installed([TOKENS["font"]["family"], "Roboto"]) + ["DejaVu Sans"], "font.size": 10,
        "figure.facecolor": PAL["surface"], "axes.facecolor": PAL["surface"], "savefig.facecolor": PAL["surface"],
        "axes.edgecolor": PAL["border"], "axes.labelcolor": PAL["ink_2"], "text.color": PAL["ink"],
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": PAL["border"], "grid.linestyle": "-", "grid.linewidth": 0.6,
        "xtick.color": PAL["ink_2"], "ytick.color": PAL["ink_2"], "xtick.labelsize": 9, "ytick.labelsize": 9,
        "xtick.major.size": 0, "ytick.major.size": 0,
        "axes.prop_cycle": plt.cycler(color=PAL["categorical"]),
        "legend.frameon": False, "legend.fontsize": 9,
    })


def finish(fig, ax, title: str, subtitle: str, path: str | Path | None = None, source: str = SOURCE,
           top: float = 0.80, left: float | None = None) -> None:
    """Left-aligned title and subtitle above the plot, source line below, then save."""
    fig.subplots_adjust(top=top, bottom=0.16, **({"left": left} if left else {}))
    x0 = ax.get_position().x0
    fig.text(x0, 0.95, title, fontsize=14, fontweight="semibold", color=PAL["ink"], va="top")
    fig.text(x0, 0.885, subtitle, fontsize=10, color=PAL["ink_2"], va="top")
    fig.text(x0, 0.03, source, fontsize=8.5, color=PAL["muted"])
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=180)
