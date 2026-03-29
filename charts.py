"""
charts.py
---------
Generates performance charts as PNG files using matplotlib.
Cross-platform replacement for the VBA BuildDashboardCharts sub.

Requires: pip install matplotlib
"""

import os
from collections import defaultdict
from datetime    import datetime

from settings  import Settings
from error_log import ErrorLog


def build_all_charts(
    dept_trends:   list[dict],
    top_performers: list[dict],
    weekly_summary: list[dict],
    settings:       Settings,
    error_log:      ErrorLog,
) -> list[str]:
    """
    Renders all dashboard charts and saves them as PNGs.
    Returns a list of saved file paths.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  [Warning] matplotlib not installed — skipping charts.")
        print("            Run: pip install matplotlib")
        return []

    out_dir = settings.get_output_dir()
    stamp   = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    saved   = []

    # Chart 1: UPH trends over time, one line per department
    path = _uph_trend_chart(dept_trends, out_dir, stamp, plt)
    if path:
        saved.append(path)

    # Chart 2: Top 10 performers horizontal bar
    path = _top_performers_chart(top_performers, out_dir, stamp, plt)
    if path:
        saved.append(path)

    # Chart 3: Department comparison (average UPH column chart)
    path = _dept_comparison_chart(dept_trends, out_dir, stamp, plt)
    if path:
        saved.append(path)

    # Chart 4: Total units trend (weekly)
    path = _units_trend_chart(weekly_summary, out_dir, stamp, plt)
    if path:
        saved.append(path)

    if saved:
        print(f"  ✓  {len(saved)} chart(s) saved to {out_dir}")

    return saved


# ── Individual chart builders ─────────────────────────────────────────────────

def _uph_trend_chart(trends: list[dict], out_dir: str, stamp: str, plt) -> str:
    if not trends:
        return ""

    # Collect unique months and departments
    months = sorted({r["Month"] for r in trends})
    depts  = sorted({r["Department"] for r in trends})

    # Build lookup: (month, dept) → avg_uph
    lookup = {(r["Month"], r["Department"]): r["Average UPH"] for r in trends}

    fig, ax = plt.subplots(figsize=(12, 6))
    for dept in depts:
        values = [lookup.get((m, dept)) for m in months]
        ax.plot(months, values, marker="o", label=dept, linewidth=2)

    ax.set_title("Department UPH Trends Over Time", fontsize=14, fontweight="bold")
    ax.set_xlabel("Month")
    ax.set_ylabel("Average UPH")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.25), ncol=4)
    ax.grid(axis="y", alpha=0.3)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    return _save_chart(fig, plt, out_dir, f"chart_uph_trends_{stamp}.png")


def _top_performers_chart(ranked: list[dict], out_dir: str, stamp: str, plt) -> str:
    if not ranked:
        return ""

    top10  = ranked[:10]
    names  = [r.get("Employee Name", "") for r in reversed(top10)]
    values = [r.get("Average UPH", 0)    for r in reversed(top10)]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(names, values, color="#1F497D", edgecolor="white")

    # Label each bar
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}", va="center", fontsize=9)

    ax.set_title(f"Top {len(top10)} Performers by Average UPH", fontsize=14, fontweight="bold")
    ax.set_xlabel("Average UPH")
    ax.set_xlim(0, max(values) * 1.15 if values else 1)
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()

    return _save_chart(fig, plt, out_dir, f"chart_top_performers_{stamp}.png")


def _dept_comparison_chart(trends: list[dict], out_dir: str, stamp: str, plt) -> str:
    if not trends:
        return ""

    # Average UPH across all months per department
    dept_totals: dict[str, list] = defaultdict(list)
    for r in trends:
        dept_totals[r["Department"]].append(r["Average UPH"])

    depts  = sorted(dept_totals.keys())
    avgs   = [sum(dept_totals[d]) / len(dept_totals[d]) for d in depts]

    fig, ax = plt.subplots(figsize=(10, 6))
    colours = ["#1F497D", "#4472C4", "#70AD47", "#ED7D31", "#A9D18E",
               "#FFD966", "#9E480E", "#833C00"]
    ax.bar(depts, avgs,
           color=[colours[i % len(colours)] for i in range(len(depts))],
           edgecolor="white")

    for i, (dept, avg) in enumerate(zip(depts, avgs)):
        ax.text(i, avg + 0.1, f"{avg:.1f}", ha="center", va="bottom", fontsize=9)

    ax.set_title("Department Performance Comparison", fontsize=14, fontweight="bold")
    ax.set_ylabel("Average UPH")
    ax.grid(axis="y", alpha=0.3)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()

    return _save_chart(fig, plt, out_dir, f"chart_dept_comparison_{stamp}.png")


def _units_trend_chart(weekly: list[dict], out_dir: str, stamp: str, plt) -> str:
    if not weekly:
        return ""

    depts  = sorted({r["Department"] for r in weekly})
    weeks  = sorted({r["Week"] for r in weekly},
                    key=lambda w: int(w.lstrip("Ww")) if w.lstrip("Ww").isdigit() else 0)
    lookup = {(r["Department"], r["Week"]): r.get("Total Units", 0) for r in weekly}

    fig, ax = plt.subplots(figsize=(12, 6))
    for dept in depts:
        values = [lookup.get((dept, w), 0) for w in weeks]
        ax.plot(weeks, values, marker="s", label=dept, linewidth=2)

    ax.set_title("Total Units by Department Over Time (Weekly)", fontsize=14, fontweight="bold")
    ax.set_xlabel("Week")
    ax.set_ylabel("Total Units")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.25), ncol=4)
    ax.grid(axis="y", alpha=0.3)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    return _save_chart(fig, plt, out_dir, f"chart_units_trend_{stamp}.png")


# ── Shared save helper ────────────────────────────────────────────────────────

def _save_chart(fig, plt, out_dir: str, filename: str) -> str:
    path = os.path.join(out_dir, filename)
    try:
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return path
    except Exception as e:
        print(f"  [Warning] Could not save chart '{filename}': {e}")
        plt.close(fig)
        return ""
