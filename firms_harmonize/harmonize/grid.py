"""Aggregate filtered detections into a cell x month x platform panel."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import PLATFORM_START, Settings
from .filters import fine_cell

VARS = ["n_det", "n_px", "n_px_day", "n_px_night", "frp_sum", "n_days"]


def add_cells(df: pd.DataFrame, s: Settings) -> pd.DataFrame:
    d = s.grid_deg
    iy = np.floor((df.lat + 90.0) / d).astype("int64")
    ix = np.floor((df.lon + 180.0) / d).astype("int64")
    return df.assign(
        cell=iy * 100_000 + ix,
        cell_lat=np.round(-90.0 + (iy + 0.5) * d, 6),
        cell_lon=np.round(-180.0 + (ix + 0.5) * d, 6),
        fine=fine_cell(df.lat, df.lon, s.dedup_deg),
        ym=df.date.dt.to_period("M").dt.to_timestamp(),
    )


def _monthly_by_platform(df: pd.DataFrame) -> pd.DataFrame:
    """One row per platform, cell, month."""
    day = df.daynight.eq("D")
    # unique ~1 km active cells per platform, day, cell, day/night
    px = (
        df.assign(dn=np.where(day, "D", "N"))
        .drop_duplicates(["platform", "date", "dn", "fine"])
        .groupby(["platform", "cell", "ym", "dn"]).size()
        .unstack("dn", fill_value=0)
        .reindex(columns=["D", "N"], fill_value=0)
        .rename(columns={"D": "n_px_day", "N": "n_px_night"})
    )
    px["n_px"] = px.n_px_day + px.n_px_night
    base = df.groupby(["platform", "cell", "ym"]).agg(
        n_det=("lat", "size"), frp_sum=("frp", "sum"), n_days=("date", "nunique")
    )
    return base.join(px).fillna(0).reset_index()


def platform_availability(df: pd.DataFrame, end_date: pd.Timestamp) -> pd.DataFrame:
    """Month by platform table: True when the platform was delivering data.

    Starts from nominal operating windows, then marks a month missing when a
    platform reports zero detections in the whole region while the other
    platforms report plenty (a data outage rather than a quiet month).
    """
    months = pd.date_range(df.ym.min(), end_date.to_period("M").to_timestamp(), freq="MS")
    plats = list(PLATFORM_START)
    avail = pd.DataFrame(False, index=months, columns=plats)
    first_seen = df.groupby("platform").date.min()
    last_seen = df.groupby("platform").date.max()
    month_start = lambda d: d.to_period("M").to_timestamp()
    for p in plats:
        if p not in last_seen:
            continue
        # Start: a month that begins more than a few days into the record is partial, so skip it
        first = max(first_seen[p], pd.Timestamp(PLATFORM_START[p]))
        start = month_start(first)
        if first.day > 3:
            start += pd.offsets.MonthBegin(1)
        # End: a platform that stops well before the others (e.g. an NRT feed that
        # lags) loses its last, partial month instead of reporting it as quiet
        last = last_seen[p]
        if last >= end_date - pd.Timedelta(days=3):
            end = month_start(end_date)
        else:
            end = month_start(last)
            if (last + pd.Timedelta(days=3)).month == last.month:
                end -= pd.offsets.MonthBegin(1)
        avail.loc[(avail.index >= start) & (avail.index <= end), p] = True

    totals = df.groupby(["ym", "platform"]).size().unstack(fill_value=0).reindex(
        index=months, columns=plats, fill_value=0
    )
    others_max = totals.apply(lambda col: totals.drop(columns=col.name).max(axis=1))
    outage = (totals == 0) & (others_max >= 50)
    avail = avail & ~outage
    return avail


def build_panel(df: pd.DataFrame, s: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wide panel: one row per cell and month, columns `<platform>_<var>`.

    A platform's columns are 0 for months it was flying with no detections in
    that cell, and NaN for months it was not available.
    """
    df = add_cells(df, s)
    end_date = df.date.max()
    avail = platform_availability(df, end_date)
    m = _monthly_by_platform(df)

    wide = m.pivot_table(index=["cell", "ym"], columns="platform", values=VARS, fill_value=0)
    wide.columns = [f"{p}_{v}" for v, p in wide.columns]

    cells = df.groupby("cell")[["cell_lat", "cell_lon"]].first()
    full_idx = pd.MultiIndex.from_product([cells.index, avail.index], names=["cell", "ym"])
    panel = wide.reindex(full_idx).reset_index()

    for p in avail.columns:
        cols = [f"{p}_{v}" for v in VARS]
        for c in cols:
            if c not in panel:
                panel[c] = np.nan
        on = panel.ym.map(avail[p]).astype(bool).to_numpy()
        panel.loc[on, cols] = panel.loc[on, cols].fillna(0)
        panel.loc[~on, cols] = np.nan

    # 32-bit floats halve memory for country-sized runs without affecting the counts
    num = [c for c in panel.columns if c.split("_", 1)[0] in avail.columns]
    panel[num] = panel[num].astype("float32")
    panel = panel.join(cells, on="cell")
    panel["year"] = panel.ym.dt.year
    panel["month"] = panel.ym.dt.month
    return panel, avail
