"""Quality and source filters applied before gridding."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Settings


def fine_cell(lat: pd.Series, lon: pd.Series, deg: float) -> pd.Series:
    iy = np.floor((lat + 90.0) / deg).astype("int64")
    ix = np.floor((lon + 180.0) / deg).astype("int64")
    return iy * 1_000_000 + ix


def static_source_cells(df: pd.DataFrame, s: Settings) -> set[int]:
    """Find ~1 km cells that behave like persistent industrial heat sources.

    Agricultural and wildland fires are seasonal. Gas flares, kilns, steel plants
    and similar sources fire through most of the year, year after year. A cell is
    flagged when it is active in many calendar months, in a large share of all
    record months, across several years. All platforms are pooled for this test.
    """
    cell = fine_cell(df.lat, df.lon, s.dedup_deg)
    ym = df.date.dt.year * 12 + df.date.dt.month - 1
    g = pd.DataFrame({"cell": cell, "ym": ym, "moy": df.date.dt.month, "yr": df.date.dt.year})
    g = g.drop_duplicates(["cell", "ym"])
    n_record_months = int(ym.max() - ym.min() + 1)
    stats = g.groupby("cell").agg(
        n_months=("ym", "nunique"), n_moy=("moy", "nunique"), n_years=("yr", "nunique")
    )
    flag = (
        (stats.n_moy >= s.static_min_calendar_months)
        & (stats.n_months / n_record_months >= s.static_min_month_fraction)
        & (stats.n_years >= s.static_min_years)
    )
    return set(stats.index[flag])


def apply_filters(df: pd.DataFrame, s: Settings) -> tuple[pd.DataFrame, dict]:
    log = {"input": len(df)}
    out = df

    if s.vegetation_only:
        keep = out["type"].isna() | (out["type"] == 0)
        log["dropped_non_vegetation_type"] = int((~keep).sum())
        out = out[keep]

    is_modis = out.sensor == "MODIS"
    ok_modis = is_modis & (out.confidence >= s.modis_min_confidence)
    letter = out.confidence_raw.str.strip().str.lower().str[0]
    ok_viirs = (~is_modis) & letter.isin(list(s.viirs_keep_confidence))
    keep = ok_modis | ok_viirs
    log["dropped_low_confidence"] = int((~keep).sum())
    out = out[keep]

    if s.mask_static_sources:
        static = static_source_cells(out, s)
        cell = fine_cell(out.lat, out.lon, s.dedup_deg)
        keep = ~cell.isin(static)
        log["static_cells_found"] = len(static)
        log["dropped_static_sources"] = int((~keep).sum())
        out = out[keep]

    log["output"] = len(out)
    return out.reset_index(drop=True), log
