"""MODIS / VIIRS hotspot harmonization pipeline (NASA Space Apps 2026).

Usage
  python run_pipeline.py --input data/firms_punjab --region punjab_pk --out outputs/punjab
  python run_pipeline.py --demo            # synthetic test data, no download needed
"""

from __future__ import annotations

import argparse
import json
import os
import time

import joblib
import numpy as np
import pandas as pd

from harmonize import calendar as cal
from harmonize.config import REGIONS, Settings
from harmonize.filters import apply_filters
from harmonize.grid import build_panel
from harmonize.load import load_folder
from harmonize.model import fit_all, harmonize
from harmonize.validate import backcast_test, by_year, leave_one_year_out

PLATFORMS = ["Terra", "Aqua", "SNPP", "NOAA20", "NOAA21"]


def step(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="folder with FIRMS CSV files")
    ap.add_argument("--region", default="punjab_pk", help=f"one of {list(REGIONS)} or 'none'")
    ap.add_argument("--bbox", help="custom lon0,lat0,lon1,lat1 (overrides --region)")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--grid", type=float, default=0.1, help="analysis grid in degrees")
    ap.add_argument("--skip-validation", action="store_true")
    ap.add_argument("--loyo-folds", type=int, default=None,
                    help="test only this many evenly spread years in leave-one-year-out (faster for big countries)")
    ap.add_argument("--demo", action="store_true", help="generate and use synthetic data")
    a = ap.parse_args()

    s = Settings(grid_deg=a.grid)
    if a.demo:
        from harmonize.synthetic import generate
        a.input = a.input or "data/synthetic_punjab"
        if not os.path.isdir(a.input):
            step("Generating synthetic FIRMS files (test data, not real)")
            generate(a.input)
    if not a.input:
        ap.error("--input is required unless --demo is used")
    bbox = tuple(map(float, a.bbox.split(","))) if a.bbox else REGIONS.get(a.region)
    os.makedirs(a.out, exist_ok=True)
    fig = lambda name: os.path.join(a.out, name)

    step(f"Loading FIRMS files from {a.input}")
    det = load_folder(a.input, bbox)
    step(f"  {len(det):,} detections, {det.date.min():%Y-%m-%d} to {det.date.max():%Y-%m-%d}")
    print(det.groupby("platform").size().reindex(PLATFORMS).dropna().astype(int).to_string())

    step("Filtering (vegetation type, confidence, persistent static sources)")
    det, flog = apply_filters(det, s)
    for k, v in flog.items():
        print(f"  {k}: {v:,}")
    data_end = det.date.max()
    with open(fig("run_settings.json"), "w") as f:
        json.dump({"input": a.input, "bbox": bbox, "grid_deg": s.grid_deg,
                   "reference_platform": s.reference_platform,
                   "data_end": data_end.strftime("%Y-%m-%d")}, f, indent=2)
    settings_path = fig("run_settings.json")
    det.to_parquet(fig("detections_clean.parquet"), index=False)

    step(f"Gridding to {s.grid_deg} degree cells and months")
    panel, avail = build_panel(det, s)
    step(f"  panel: {panel.cell.nunique():,} cells x {panel.ym.nunique()} months")
    outages = {p: [d.strftime("%Y-%m") for d in avail.index[~avail[p]]
                   if avail[p].loc[:d].any() and avail[p].loc[d:].any()]
               for p in avail.columns}
    for p, months in outages.items():
        if months:
            print(f"  data gap detected for {p}: {', '.join(months)}")

    metrics = None
    if not a.skip_validation:
        step("Leave one year out validation in the overlap period")
        preds, metrics = leave_one_year_out(panel, s, a.loyo_folds)
        metrics.to_csv(fig("validation_metrics.csv"), index=False)
        print(metrics.to_string(index=False))
        yearly = by_year(preds, s)
        yearly.to_csv(fig("validation_by_year.csv"), index_label="year")
        print(yearly.to_string())
        step("Backcast test: train on later years, predict the earliest VIIRS years")
        bc_years, bc = backcast_test(panel, s)
        bc_years.to_csv(fig("validation_backcast_by_year.csv"), index_label="year")
        print(json.dumps(bc, indent=2))
        print(bc_years.to_string())
        # Pick the model that rebuilds unseen earlier years best. A model with a large
        # bias is never chosen, whatever its error.
        g, r = bc["pred_gbm_aqua"], bc["pred_ratio"]
        # error and bias both count: a model that is 10% off overall scores twice its error
        score = lambda m: m["mae"] * (1 + abs(m["bias_pct"]) / 10) if np.isfinite(m["mae"]) else np.inf
        s.extra["primary_model"] = "gbm" if score(g) <= score(r) else "ratio"
        step(f"Model chosen for rebuilding pre-2012 years: {s.extra['primary_model']} "
             f"(backcast MAE gbm {g['mae']:.0f}, ratio {r['mae']:.0f})")
        reg = preds.groupby("ym")[[f"{s.reference_platform}_n_det", "pred_gbm_aqua", "pred_ratio"]].sum()
        reg = reg.reindex(pd.date_range(reg.index.min(), reg.index.max(), freq="MS"))
        cal.plot_lines(
            reg,
            {f"{s.reference_platform}_n_det": ("VIIRS S-NPP observed", cal.SERIES["blue"]),
             "pred_gbm_aqua": ("Predicted from MODIS (held-out year)", cal.SERIES["orange"])},
            "Held-out years: VIIRS observed vs reconstructed from MODIS",
            "Hotspots per month", fig("validation_monthly.png"), direct_labels=False,
        )

    step("Fitting final models on the full overlap and building the harmonized series")
    models = fit_all(panel, s)
    run_meta = json.load(open(settings_path))
    run_meta["primary_model"] = s.extra.get("primary_model", "gbm")
    json.dump(run_meta, open(settings_path, "w"), indent=2)
    joblib.dump(models, fig("models.joblib"))
    harm = harmonize(panel, models, s)
    harm.to_parquet(fig("harmonized_cell_month.parquet"), index=False)
    harm.to_csv(fig("harmonized_cell_month.csv.gz"), index=False)
    print(harm.groupby("source").size().to_string())

    step("Calendar for the whole region")
    series = cal.monthly_series(harm)
    share = cal.expected_share_to_day(det, data_end, s.reference_platform)
    table = cal.calendar_table(series, s.baseline_years, data_end=data_end, partial_share=share)
    table.to_csv(fig("calendar_region.csv"), index_label="month_start")
    summ = cal.summary(table)
    print(json.dumps(summ, indent=2))
    name = a.region if not a.bbox else "custom area"
    cal.plot_calendar(table, f"Burning activity calendar, {name} (harmonized hotspots)", fig("calendar_counts.png"))
    cal.plot_calendar(table, f"Monthly anomaly vs historical median, {name}", fig("calendar_anomaly.png"), anomaly=True)

    step("Break check: does the record jump when new satellites arrive?")
    raw = panel.assign(all_platforms=panel[[f"{p}_n_det" for p in PLATFORMS]].sum(axis=1, min_count=1))
    ann = pd.DataFrame({
        "raw_all": raw.groupby("year").all_platforms.sum(),
        "aqua_only": panel.groupby("year")["Aqua_n_det"].sum(min_count=1),
        "harmonized": harm.groupby("year").harmonized.sum(),
    })
    nmonths = harm.groupby("year").ym.nunique()
    ann = ann[nmonths.reindex(ann.index) == 12]
    ann.round(0).to_csv(fig("annual_totals.csv"), index_label="year")
    cal.plot_lines(
        ann,
        {"raw_all": ("All satellites pooled (raw)", cal.SERIES["orange"]),
         "aqua_only": ("Aqua MODIS only (raw)", cal.SERIES["aqua"]),
         "harmonized": ("Harmonized (S-NPP equivalent)", cal.SERIES["blue"])},
        "Annual hotspot totals: raw records vs harmonized",
        "Hotspots per year", fig("break_check.png"),
        vlines={2012: "S-NPP", 2018: "NOAA-20", 2023: "NOAA-21"},
    )

    truth_file = os.path.join(a.input, "TRUTH_monthly_true_fires.txt")
    truth_note = ""
    if os.path.exists(truth_file):
        step("Synthetic truth available: checking ratio to true fire counts")
        truth = pd.read_csv(truth_file, parse_dates=["ym"]).set_index("ym").true_fires
        ty = truth.groupby(truth.index.year).sum().reindex(ann.index)
        rel = (ann.div(ty, axis=0))
        rel = rel / rel.loc[[y for y in rel.index if 2003 <= y <= 2011]].mean()
        rel.round(3).to_csv(fig("synthetic_ratio_to_truth.csv"), index_label="year")
        cal.plot_lines(
            rel,
            {"raw_all": ("All satellites pooled (raw)", cal.SERIES["orange"]),
             "aqua_only": ("Aqua MODIS only (raw)", cal.SERIES["aqua"]),
             "harmonized": ("Harmonized (S-NPP equivalent)", cal.SERIES["blue"])},
            "Synthetic test: detections per true fire, indexed to 2003 to 2011 = 1",
            "Ratio to true fires (indexed)", fig("synthetic_truth_check.png"),
            vlines={2012: "S-NPP", 2018: "NOAA-20", 2023: "NOAA-21"},
        )
        pre = rel.loc[2003:2011].mean()
        post = rel.loc[2013:2023].mean()
        truth_note = "\n".join(
            f"| {c} | {pre[c]:.2f} | {post[c]:.2f} | {(post[c] / pre[c] - 1) * 100:+.0f}% |" for c in rel.columns
        )
        print(rel.loc[[2010, 2011, 2012, 2013, 2019, 2025]].round(2).to_string())

    step("Writing report")
    with open(fig("REPORT.md"), "w") as f:
        f.write("# Harmonization run report\n\n")
        f.write(f"Input: `{a.input}`  \nRegion: {name} {bbox}  \nGrid: {s.grid_deg} degrees\n\n")
        f.write("## Filtering\n\n" + "\n".join(f"- {k}: {v:,}" for k, v in flog.items()) + "\n\n")
        gaps = {p: m for p, m in outages.items() if m}
        if gaps:
            f.write("## Detected data gaps\n\n" + "\n".join(f"- {p}: {', '.join(m)}" for p, m in gaps.items()) + "\n\n")
        if metrics is not None:
            f.write("## Leave one year out validation\n\n" + metrics.to_markdown(index=False) + "\n\n")
            f.write("### Annual totals for each held-out year (gradient boosting)\n\n" + yearly.to_markdown() + "\n\n")
            f.write(f"Model used to rebuild pre-2012 years: **{s.extra.get('primary_model', 'gbm')}**\n\n")
            f.write(f"## Backcast test\n\nTrained on {bc['train_years']}, predicted {bc['test_years']} "
                    "(the same backward direction used to rebuild 2000 to 2011).\n\n")
            f.write("| model | region-month r | MAE | bias % |\n|---|---|---|---|\n")
            for k in ("pred_gbm_aqua", "pred_ratio"):
                f.write(f"| {k} | {bc[k]['pearson_r']} | {bc[k]['mae']} | {bc[k]['bias_pct']} |\n")
            f.write("\n" + bc_years.to_markdown() + "\n\n")
        f.write("## Sources used in the harmonized series (cell-months)\n\n")
        f.write(harm.groupby("source").size().rename("cell_months").to_markdown() + "\n\n")
        f.write("## Region summary\n\n```json\n" + json.dumps(summ, indent=2) + "\n```\n\n")
        if truth_note:
            f.write("## Synthetic truth check (detections per true fire, indexed)\n\n")
            f.write("| series | 2003 to 2011 | 2013 to 2023 | change |\n|---|---|---|---|\n" + truth_note + "\n")
    step(f"Done. Outputs in {a.out}")


if __name__ == "__main__":
    main()
