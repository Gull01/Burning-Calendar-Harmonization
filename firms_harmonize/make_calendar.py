"""Calendar and downloads for any area, from an existing pipeline run.

This is the query the web app will run behind its map: pick an area and a date
range, get the calendar, the anomaly view, a summary, and CSV files.

Examples
  python make_calendar.py --run outputs/punjab --point 74.35,31.55 --radius 40
  python make_calendar.py --run outputs/punjab --bbox 72.5,30.0,74.5,31.5 --start 2003-01 --end 2026-10
  python make_calendar.py --run outputs/punjab --polygon "73,30 74,30 74,31 73,31"
"""

from __future__ import annotations

import argparse
import json
import os

import pandas as pd

from harmonize import calendar as cal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="output folder of run_pipeline.py")
    ap.add_argument("--bbox", help="lon0,lat0,lon1,lat1")
    ap.add_argument("--polygon", help="'lon,lat lon,lat ...'")
    ap.add_argument("--point", help="lon,lat (use with --radius)")
    ap.add_argument("--radius", type=float, help="km")
    ap.add_argument("--start", help="YYYY-MM")
    ap.add_argument("--end", help="YYYY-MM")
    ap.add_argument("--name", default="selected area")
    ap.add_argument("--out", help="folder for results (default: <run>/area)")
    a = ap.parse_args()

    with open(os.path.join(a.run, "run_settings.json")) as f:
        run = json.load(f)
    harm = pd.read_parquet(os.path.join(a.run, "harmonized_cell_month.parquet"))
    det = pd.read_parquet(os.path.join(a.run, "detections_clean.parquet"))
    out = a.out or os.path.join(a.run, "area")
    os.makedirs(out, exist_ok=True)

    kw = {}
    if a.bbox:
        kw["bbox"] = tuple(map(float, a.bbox.split(",")))
    if a.polygon:
        kw["polygon"] = [tuple(map(float, p.split(","))) for p in a.polygon.split()]
    if a.point:
        kw["point"] = tuple(map(float, a.point.split(",")))
        kw["radius_km"] = a.radius or 25
    sel = cal.select_cells(harm, **kw)
    if sel.empty:
        raise SystemExit("No grid cells in that area")

    from harmonize.config import Settings
    from harmonize.grid import add_cells
    s = Settings(grid_deg=run["grid_deg"])
    d = add_cells(det, s)
    d = d[d.cell.isin(sel.cell.unique())]

    start = pd.Timestamp(a.start) if a.start else None
    end = pd.Timestamp(a.end) if a.end else None
    series = cal.monthly_series(sel, start, end)
    data_end = run.get("data_end")
    share = cal.expected_share_to_day(d, data_end, run.get("reference_platform", "SNPP")) if data_end else None
    table = cal.calendar_table(series, data_end=data_end, partial_share=share)
    table.to_csv(os.path.join(out, "calendar.csv"), index_label="month_start")
    summ = cal.summary(table)
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump(summ, f, indent=2)
    cal.plot_calendar(table, f"Burning activity calendar, {a.name}", os.path.join(out, "calendar_counts.png"))
    cal.plot_calendar(table, f"Anomaly vs historical median, {a.name}", os.path.join(out, "calendar_anomaly.png"), anomaly=True)

    # raw detections inside the same cells, for the CSV download
    if start is not None:
        d = d[d.date >= start]
    if end is not None:
        d = d[d.date < end + pd.offsets.MonthBegin(1)]
    cols = ["lat", "lon", "date", "time_utc", "platform", "sensor", "confidence_raw", "frp", "daynight"]
    d[cols].to_csv(os.path.join(out, "hotspots_in_area.csv"), index=False)

    print(json.dumps(summ, indent=2))
    print(f"{sel.cell.nunique()} cells, {len(d):,} raw detections -> {out}")


if __name__ == "__main__":
    main()
