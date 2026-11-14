"""Export a pipeline run into compact static files for the web app.

  python build_webapp_data.py --run outputs/pakistan --data ../webapp/data --id pakistan --name "Pakistan"

Each region goes to <data>/<id>/, and <data>/regions.json lists all regions for the app's switcher.

Writes
  meta.json           grid, cells, months, per-month data source, validation, method charts
  harmonized.bin      Uint16, cells x months, value x 100 (65535 = no data)
  det_<year>.bin      filtered raw detections per year, columnar (see LAYOUT below)
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from harmonize.config import Settings
from harmonize.grid import add_cells

PLATFORMS = ["Terra", "Aqua", "SNPP", "NOAA20", "NOAA21"]
# Per detection, blocks in this order (layout 2, 15 bytes per detection):
#   lat_off u16, lon_off u16 (position inside the grid cell, 0..65535 across one cell),
#   frp u16 (MW x 10, capped), day u16 (days since 2000-01-01), time u16 (HHMM UTC),
#   cell u16 (index into meta.cells), platform u8, conf u8, daynight u8 (1 = day)
LAYOUT = ["lat_off:u16", "lon_off:u16", "frp10:u16", "day:u16", "time:u16", "cell:u16", "platform:u8", "conf:u8", "dn:u8"]
EPOCH = pd.Timestamp("2000-01-01")
MISSING = 65535


def source_label(src: str) -> str:
    if src.startswith("VIIRS_SNPP"):
        return "viirs"
    if src.startswith("VIIRS_"):
        return "viirs_scaled"
    if "Aqua" in src:
        return "modis_aqua"
    if "Terra" in src:
        return "modis_terra"
    return "none"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--data", required=True, help="the web app's data folder")
    ap.add_argument("--id", required=True, help="short folder name, e.g. pakistan")
    ap.add_argument("--name", required=True, help="name shown in the app, e.g. Pakistan")
    ap.add_argument("--order", type=int, default=None, help="position in the region list")
    ap.add_argument("--note", default="", help="short caveat shown in the app for this region")
    a = ap.parse_args()
    a.out = os.path.join(a.data, a.id)
    os.makedirs(a.out, exist_ok=True)

    run = json.load(open(os.path.join(a.run, "run_settings.json")))
    s = Settings(grid_deg=run["grid_deg"])
    data_end = pd.Timestamp(run["data_end"])

    harm = pd.read_parquet(os.path.join(a.run, "harmonized_cell_month.parquet"))
    cells = harm.groupby("cell")[["cell_lat", "cell_lon"]].first().sort_index()
    if len(cells) >= 65535:
        raise SystemExit(f"{len(cells)} grid cells is too many for this format; use a coarser --grid in run_pipeline.py")
    cell_index = pd.Series(np.arange(len(cells)), index=cells.index)
    months = pd.date_range(harm.ym.min(), harm.ym.max(), freq="MS")
    month_index = pd.Series(np.arange(len(months)), index=months)

    # harmonized matrix
    mat = np.full((len(cells), len(months)), MISSING, dtype=np.uint16)
    ok = harm.harmonized.notna()
    ci = cell_index.reindex(harm.cell[ok]).to_numpy()
    mi = month_index.reindex(harm.ym[ok]).to_numpy()
    mat[ci, mi] = np.clip(np.round(harm.harmonized[ok].to_numpy() * 100), 0, MISSING - 1).astype(np.uint16)
    mat.tofile(os.path.join(a.out, "harmonized.bin"))

    src = harm.groupby("ym").source.agg(lambda x: x.mode().iat[0] if len(x) else "")
    month_source = [source_label(src.get(m, "")) for m in months]

    # detections per year
    det = pd.read_parquet(os.path.join(a.run, "detections_clean.parquet"))
    det = add_cells(det, s)
    det["ci"] = cell_index.reindex(det.cell).to_numpy()
    det = det[det.ci.notna()]
    years = {}
    for yr, d in det.groupby(det.date.dt.year):
        d = d.sort_values(["date", "time_utc"])
        conf = np.where(d.sensor == "MODIS", d.confidence.fillna(0), np.where(d.confidence >= 100, 100, 50))
        g = s.grid_deg
        ci = d.ci.to_numpy(np.int64)
        lat0 = cells.cell_lat.to_numpy()[ci] - g / 2
        lon0 = cells.cell_lon.to_numpy()[ci] - g / 2
        off = lambda v, v0: np.clip(np.round((v - v0) / g * 65535), 0, 65535).astype(np.uint16)
        blocks = [
            off(d.lat.to_numpy(), lat0), off(d.lon.to_numpy(), lon0),
            np.clip(np.round(d.frp.fillna(0).to_numpy() * 10), 0, 65535).astype(np.uint16),
            (d.date - EPOCH).dt.days.to_numpy(np.uint16), d.time_utc.fillna(0).to_numpy(np.uint16),
            ci.astype(np.uint16), d.platform.map({p: i for i, p in enumerate(PLATFORMS)}).to_numpy(np.uint8),
            np.clip(conf, 0, 255).astype(np.uint8), (d.daynight == "D").to_numpy(np.uint8),
        ]
        with open(os.path.join(a.out, f"det_{yr}.bin"), "wb") as f:
            for b in blocks:
                f.write(b.tobytes())
        years[int(yr)] = int(len(d))

    # typical share of the current month's hotspots seen by data_end's day, per cell and past year
    partial = None
    if data_end.day < data_end.days_in_month:
        ref = det[(det.platform == run.get("reference_platform", "SNPP"))
                  & (det.date.dt.month == data_end.month) & (det.date.dt.year < data_end.year)]
        g = ref.groupby([ref.date.dt.year, "ci"]).date.agg(
            total="size", by_day=lambda x: int((x.dt.day <= data_end.day).sum()))
        pyears = sorted(g.index.get_level_values(0).unique())
        by, tot = {}, {}
        for (yr, c), r in g.iterrows():
            k = str(int(c))
            by.setdefault(k, [0] * len(pyears))[pyears.index(yr)] = int(r.by_day)
            tot.setdefault(k, [0] * len(pyears))[pyears.index(yr)] = int(r.total)
        partial = {"day": data_end.day, "days_in_month": data_end.days_in_month,
                   "years": [int(y) for y in pyears], "by_day": by, "total": tot}

    # method page material
    ann = pd.read_csv(os.path.join(a.run, "annual_totals.csv"))
    metrics = pd.read_csv(os.path.join(a.run, "validation_metrics.csv"))
    primary = run.get("primary_model", "gbm")
    pred_col = "pred_gbm_aqua" if primary == "gbm" else "pred_ratio"
    loyo = metrics[(metrics.model == pred_col) & (metrics.scale == "region-month")].iloc[0]
    bc = pd.read_csv(os.path.join(a.run, "validation_backcast_by_year.csv"))  # per-year table is for gbm
    report = open(os.path.join(a.run, "REPORT.md")).read()
    bc_r = None
    for line in report.splitlines():
        if line.startswith(f"| {pred_col} |"):
            parts = [p.strip() for p in line.strip("|").split("|")]
            bc_r = {"r": float(parts[1]), "bias_pct": float(parts[3])}

    meta = {
        "region": a.name,
        "short_name": a.name,
        "note": a.note,
        "id": a.id,
        "bbox": run["bbox"],
        "grid_deg": s.grid_deg,
        "data_end": data_end.strftime("%Y-%m-%d"),
        "first_month": months[0].strftime("%Y-%m"),
        "n_months": len(months),
        "month_source": month_source,
        "platforms": PLATFORMS,
        "epoch": "2000-01-01",
        "layout": LAYOUT,
        "layout_version": 2,
        "scale": 100,
        "missing": MISSING,
        "cells": {
            "lat": [round(v, 4) for v in cells.cell_lat],
            "lon": [round(v, 4) for v in cells.cell_lon],
        },
        "det_years": years,
        "partial": partial,
        "method": {
            "annual": {
                "year": ann.year.astype(int).tolist(),
                **{c: [None if pd.isna(v) else int(round(v)) for v in ann[c]]
                   for c in ("raw_all", "aqua_only", "harmonized")},
            },
            "model": "gradient boosting" if primary == "gbm" else "cell ratio",
            "loyo_r": float(loyo.pearson_r), "loyo_bias_pct": float(loyo.bias_pct),
            "backcast": bc_r,
            "backcast_years": {"year": bc.year.astype(int).tolist(),
                               "bias_pct": bc[f"bias_pct_{primary}" if f"bias_pct_{primary}" in bc else "bias_pct"].tolist()},
        },
    }
    with open(os.path.join(a.out, "meta.json"), "w") as f:
        json.dump(meta, f, separators=(",", ":"))

    # region list for the app
    reg_path = os.path.join(a.data, "regions.json")
    regions = json.load(open(reg_path))["regions"] if os.path.exists(reg_path) else []
    regions = [r for r in regions if r["id"] != a.id]
    entry = {"id": a.id, "name": a.name, "bbox": run["bbox"], "order": a.order if a.order is not None else len(regions)}
    regions.append(entry)
    regions.sort(key=lambda r: (r["order"], r["name"]))
    with open(reg_path, "w") as f:
        json.dump({"regions": regions}, f, indent=1)

    sizes = {f: os.path.getsize(os.path.join(a.out, f)) for f in os.listdir(a.out)}
    print(f"{len(cells)} cells, {len(months)} months, {sum(years.values()):,} detections")
    print(f"total {sum(sizes.values()) / 1e6:.1f} MB; largest {max(sizes, key=sizes.get)} "
          f"{max(sizes.values()) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
