"""Draw the pipeline diagram used in the report's technical appendix (figures/pipeline.png).

    python python/scripts/pipeline_diagram.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from marketing_analytics.style import PAL, TOKENS, apply

OUT = Path(__file__).resolve().parents[2] / "figures" / "pipeline.png"

# (x, y, title, detail, highlighted)
BOXES = {
    "ga4": (0.02, 0.42, "GA4 events", "BigQuery sample\n4.3M events, 92 days", False),
    "parquet": (0.20, 0.42, "Parquet", "one file per day", False),
    "dbt": (0.38, 0.42, "dbt + DuckDB", "25 models\n62 data tests", True),
    "python": (0.60, 0.74, "Python", "attribution, customers\n16 tests", False),
    "r": (0.60, 0.42, "R", "A/B test, forecast,\nmix model · 5 tests", False),
    "pbi": (0.60, 0.10, "Power BI", "generated from code\nschema-validated", False),
    "out": (0.81, 0.42, "Report and deck", "one design system\nnumbers from code", False),
}
W, H = 0.16, 0.2


def main() -> None:
    apply()
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    for x, y, title, detail, strong in BOXES.values():
        ax.add_patch(FancyBboxPatch((x, y), W, H, boxstyle="round,pad=0.004,rounding_size=0.015",
                                    facecolor=TOKENS["color"]["background.selected"] if strong else PAL["surface"], edgecolor=PAL["border"], lw=1))
        ax.text(x + 0.012, y + H - 0.045, title, fontsize=10.5, weight="semibold", color=PAL["ink"], va="top")
        ax.text(x + 0.012, y + H - 0.105, detail, fontsize=8.5, color=PAL["ink_2"], va="top", linespacing=1.3)

    def arrow(a, b):
        (xa, ya, *_), (xb, yb, *_) = BOXES[a], BOXES[b]
        ax.add_patch(FancyArrowPatch((xa + W, ya + H / 2), (xb, yb + H / 2), arrowstyle="-|>", mutation_scale=10,
                                     color=PAL["ink_2"], lw=1, connectionstyle="arc3,rad=0"))

    for a, b in [("ga4", "parquet"), ("parquet", "dbt"), ("dbt", "python"), ("dbt", "r"), ("dbt", "pbi"),
                 ("python", "out"), ("r", "out"), ("pbi", "out")]:
        arrow(a, b)
    ax.text(0.02, 0.0, "python python/scripts/run_all.py rebuilds everything · CI runs the unit tests and compiles dbt on every push",
            fontsize=8.5, color=PAL["ink_2"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
