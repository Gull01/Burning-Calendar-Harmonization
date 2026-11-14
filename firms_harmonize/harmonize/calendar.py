"""Burning activity calendar: aggregation, anomalies and figures.

These functions only need the harmonized cell-month table, so the web app can
import them directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.path import Path

# Palette (single hue sequential ramp for counts; blue / gray / red diverging
# for anomalies, red meaning more burning than usual)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
SEQ = ["#fcfcfb", "#fde6d8", "#f8b896", "#eb6834", "#b8461a", "#6e250a"]
DIV = ["#184f95", "#5598e7", "#cde2fb", "#f0efec", "#f8c9c8", "#e34948", "#8f1d1d"]
SERIES = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def select_cells(harm: pd.DataFrame, bbox=None, polygon=None, point=None, radius_km=None):
    """Filter cells by bbox (lon0, lat0, lon1, lat1), a polygon [(lon, lat), ...],
    or a point (lon, lat) with radius in km. Uses cell centres."""
    h = harm
    if bbox is not None:
        lon0, lat0, lon1, lat1 = bbox
        h = h[h.cell_lon.between(lon0, lon1) & h.cell_lat.between(lat0, lat1)]
    if polygon is not None:
        inside = Path(np.asarray(polygon)).contains_points(h[["cell_lon", "cell_lat"]].to_numpy())
        h = h[inside]
    if point is not None and radius_km is not None:
        lon, lat = point
        dx = (h.cell_lon - lon) * 111.32 * np.cos(np.radians(lat))
        dy = (h.cell_lat - lat) * 110.57
        h = h[np.hypot(dx, dy) <= radius_km]
    return h


def monthly_series(harm_sel: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    g = harm_sel.groupby("ym").agg(
        harmonized=("harmonized", lambda x: x.sum(min_count=1)),
        modeled_share=("source", lambda s: float(s.str.startswith("MODIS").mean())),
    )
    g = g[g.harmonized.notna()]  # months with no satellite data at all
    g["harmonized"] = g.harmonized.round(1)
    if start is not None:
        g = g[g.index >= pd.Timestamp(start)]
    if end is not None:
        g = g[g.index <= pd.Timestamp(end)]
    g["year"] = g.index.year
    g["month"] = g.index.month
    return g


def expected_share_to_day(det_sel: pd.DataFrame, data_end, platform: str = "SNPP",
                          min_month_total: int = 20) -> float:
    """Typical share of a month's hotspots that occur by `data_end`'s day of month.

    Burning is not spread evenly through a month (Punjab rice residue burning is
    concentrated in early November), so "11 of 30 days" is not "37% of the month".
    Uses the reference platform's detections in the same calendar month of past
    years; falls back to the plain day fraction when there is too little history.
    """
    data_end = pd.Timestamp(data_end)
    naive = data_end.day / data_end.days_in_month
    d = det_sel[(det_sel.platform == platform) & (det_sel.date.dt.month == data_end.month)
                & (det_sel.date.dt.year < data_end.year)]
    if d.empty:
        return naive
    g = d.groupby(d.date.dt.year).date.agg(
        total="size", by_day=lambda x: int((x.dt.day <= data_end.day).sum())
    )
    g = g[g.total >= min_month_total]
    if len(g) < 3:
        return naive
    return float((g.by_day / g.total).median())


def calendar_table(series: pd.DataFrame, baseline_years=None, min_median: float = 10,
                   data_end=None, partial_share: float | None = None) -> pd.DataFrame:
    """Adds the per-month historical median, anomaly and rank.

    The anomaly is left empty for calendar months whose median is below
    `min_median` hotspots, where a percentage would be meaningless noise.

    If `data_end` falls inside the last month (the current, unfinished month),
    that month is compared with past values scaled by `partial_share` (the
    typical share of that month's hotspots seen by that day; see
    expected_share_to_day), or by the plain day fraction if none is given, so
    "so far this month" is not read as a quiet month.
    """
    t = series.copy()
    t["days_covered_frac"] = 1.0
    t["expected_share_so_far"] = 1.0
    partial_idx = None
    if data_end is not None:
        data_end = pd.Timestamp(data_end)
        last = t.index.max()
        if last == data_end.to_period("M").to_timestamp() and data_end.day < data_end.days_in_month:
            partial_idx = last
            t.loc[last, "days_covered_frac"] = round(data_end.day / data_end.days_in_month, 3)
            share = partial_share if partial_share is not None else data_end.day / data_end.days_in_month
            t.loc[last, "expected_share_so_far"] = round(share, 3)
    full = t.drop(index=partial_idx) if partial_idx is not None else t
    base = full if baseline_years is None else full[full.year.between(*baseline_years)]
    med = base.groupby("month").harmonized.median()
    mean = base.groupby("month").harmonized.mean()
    t["median_for_month"] = (t.month.map(med) * t.expected_share_so_far).round(1)
    t["mean_for_month"] = (t.month.map(mean) * t.expected_share_so_far).round(1)
    t["anomaly_vs_median_pct"] = np.where(
        t.median_for_month >= min_median,
        (t.harmonized / t.median_for_month - 1) * 100,
        np.nan,
    ).round(1)
    t["rank_among_same_month"] = full.groupby("month").harmonized.rank(ascending=False, method="min")
    t["years_of_record_for_month"] = t.groupby("month").harmonized.transform("count")
    if partial_idx is not None:
        r = t.loc[partial_idx]
        others = full[full.month == r.month].harmonized * r.expected_share_so_far
        t.loc[partial_idx, "rank_among_same_month"] = 1 + int((others > r.harmonized).sum())
    t["rank_among_same_month"] = t.rank_among_same_month.astype(int)
    return t


def summary(cal: pd.DataFrame) -> dict:
    full_years = cal.groupby("year").month.count()
    full_years = full_years[full_years == 12].index
    annual = cal[cal.year.isin(full_years)].groupby("year").harmonized.sum()
    complete = cal[cal.days_covered_frac == 1] if "days_covered_frac" in cal else cal
    by_month = complete.groupby("month").harmonized.median()
    last = cal.iloc[-1]
    return {
        "latest_month_days_covered": f"{last.days_covered_frac:.0%}" if "days_covered_frac" in cal else "100%",
        "latest_month_typical_share_by_now": f"{last.expected_share_so_far:.0%}" if "expected_share_so_far" in cal else "100%",
        "peak_calendar_month": MONTHS[int(by_month.idxmax()) - 1],
        "top_years": [int(y) for y in annual.sort_values(ascending=False).index[:3]],
        "quietest_year": int(annual.idxmin()) if len(annual) else None,
        "latest_month": last.name.strftime("%Y-%m"),
        "latest_month_hotspots": float(last.harmonized),
        "latest_month_median": float(last.median_for_month),
        "latest_month_anomaly_pct": None if pd.isna(last.anomaly_vs_median_pct) else float(last.anomaly_vs_median_pct),
        "latest_month_rank": f"{int(last.rank_among_same_month)} of {int(last.years_of_record_for_month)}",
    }


# ---------------------------------------------------------------- figures

def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9)


def plot_calendar(cal: pd.DataFrame, title: str, path: str, anomaly: bool = False, min_median: float = 10):
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, TwoSlopeNorm

    years = sorted(cal.year.unique())
    grid = np.full((len(years), 12), np.nan)
    have = np.zeros((len(years), 12), bool)
    modeled = cal.groupby("year").modeled_share.mean()
    for (yr, mo), r in cal.set_index(["year", "month"]).iterrows():
        i = years.index(yr)
        have[i, mo - 1] = True
        if anomaly:
            # anomalies of near-empty months are noise, so they are left neutral
            if r.median_for_month >= min_median:
                grid[i, mo - 1] = r.anomaly_vs_median_pct
            else:
                grid[i, mo - 1] = 0.0
        else:
            grid[i, mo - 1] = r.harmonized

    fig, ax = plt.subplots(figsize=(9, 0.28 * len(years) + 1.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    nodata = "#d9d8d3"
    if anomaly:
        ratio = np.log2(np.clip(1 + grid / 100, 0.25, 4))
        cmap = LinearSegmentedColormap.from_list("div", DIV)
        cmap.set_bad(nodata)
        im = ax.imshow(np.ma.masked_where(~have, ratio), cmap=cmap, norm=TwoSlopeNorm(0, -2, 2), aspect="auto")
        cb = fig.colorbar(im, ax=ax, ticks=[-2, -1, 0, 1, 2], fraction=0.035, pad=0.02)
        cb.ax.set_yticklabels(["4x fewer", "2x fewer", "median", "2x more", "4x more"])
    else:
        cmap = LinearSegmentedColormap.from_list("seq", SEQ)
        cmap.set_bad(nodata)
        vmax = np.nanpercentile(grid, 99)
        im = ax.imshow(np.ma.masked_where(~have, grid), cmap=cmap, vmin=0, vmax=vmax, aspect="auto")
        cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
        cb.set_label("Hotspots per month (VIIRS-equivalent)", color=INK_2, fontsize=9)
        # selective labels: the peak month of each year
        for i, yr in enumerate(years):
            row = grid[i]
            if np.all(np.isnan(row)):
                continue
            j = int(np.nanargmax(row))
            v = row[j]
            ax.text(j, i, f"{v:,.0f}", ha="center", va="center", fontsize=6.5,
                    color="white" if v > 0.55 * vmax else INK)
    cb.ax.tick_params(labelsize=8, colors=INK_2)
    cb.outline.set_visible(False)
    if "days_covered_frac" in cal:
        for idx, r in cal[cal.days_covered_frac < 1].iterrows():
            ax.text(r.month - 1, years.index(r.year) + 0.32, f"{r.days_covered_frac:.0%} of month",
                    ha="center", va="center", fontsize=5, color=INK_2)

    ax.set_xticks(range(12), MONTHS)
    labels = [f"{y}*" if modeled.get(y, 0) > 0.5 else str(y) for y in years]
    ax.set_yticks(range(len(years)), labels)
    ax.tick_params(length=0, labelsize=8, colors=INK_2)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(np.arange(-0.5, 12), minor=True)
    ax.set_yticks(np.arange(-0.5, len(years)), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=1.5)
    ax.tick_params(which="minor", length=0)
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=10)
    note = "* year mainly reconstructed from MODIS through the harmonization model.   Gray: no satellite data."
    if anomaly:
        note += f"   Months with a median under {min_median} hotspots are shown as neutral."
    fig.text(0.01, 0.005, note, fontsize=7, color=INK_2)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def plot_lines(df: pd.DataFrame, cols: dict, title: str, ylabel: str, path: str,
               vlines: dict | None = None, shade: tuple | None = None, direct_labels: bool = True):
    """df indexed by x; cols maps column -> (label, color). Gaps (NaN) break the line."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    if shade:
        ax.axvspan(*shade, color="#f0efec", zorder=0)
    for c, (label, color) in cols.items():
        ax.plot(df.index, df[c].values, color=color, linewidth=2 if direct_labels else 1.5, label=label)
        s = df[c].dropna()
        if direct_labels:
            ax.annotate(label, (s.index[-1], s.values[-1]), xytext=(6, 0), textcoords="offset points",
                        color=INK_2, fontsize=8, va="center")
    for x, lab in (vlines or {}).items():
        ax.axvline(x, color=INK_2, linewidth=0.8, linestyle=(0, (2, 3)))
        ax.text(x, ax.get_ylim()[1], f" {lab}", color=INK_2, fontsize=7.5, va="top")
    ax.set_ylabel(ylabel, color=INK_2, fontsize=9)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=8, loc="upper left", labelcolor=INK_2)
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
