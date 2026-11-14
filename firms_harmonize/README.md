# MODIS and VIIRS hotspot harmonization

Part 1 of our NASA Space Apps 2026 entry for **Harmonization of MODIS and VIIRS Hot Spots**.
It turns the split FIRMS record (MODIS since 2000, VIIRS since 2012) into one consistent
monthly hotspot series per grid cell, then builds the burning activity calendar,
anomaly view and CSV downloads the web app will serve.

## The idea in one paragraph

Raw hotspot counts jump every time a satellite is added (S-NPP in 2012, NOAA-20 in 2018,
NOAA-21 in 2023) and because VIIRS sees far more small fires than MODIS. We pick one fixed
reference, **S-NPP VIIRS detections**, so the sensor of origin stops mattering. In the overlap
years (2012 onward) we learn how what MODIS saw in a cell and month maps onto what S-NPP saw,
then use that to reconstruct VIIRS-equivalent counts for 2000 to 2011. Aqua MODIS is the main
predictor because it crosses at the same early afternoon time as S-NPP; Terra adds information
and covers the months before Aqua launched.

## Pipeline

| Step | File | What happens |
|---|---|---|
| Load | `harmonize/load.py` | Reads any FIRMS CSV (archive or NRT, MODIS C6.1 or VIIRS 375 m), detects sensor and platform, removes archive/NRT duplicates |
| Filter | `harmonize/filters.py` | Keeps vegetation fires (type 0), drops low confidence (MODIS under 30, VIIRS "l"), masks persistent industrial sources such as kilns and flares that FIRMS does not label |
| Grid | `harmonize/grid.py` | Cell x month x platform panel. Separates a real zero (satellite flying, no fire) from missing data, and detects outages automatically |
| Model | `harmonize/model.py` | Gradient boosting on log(1 + count), calibrated per calendar month, from same-month MODIS features (counts, unique ~1 km pixels, day/night, FRP, neighbourhood activity at 0.5 and 2 degrees) to S-NPP counts. A shrunken ratio model is kept as a transparent baseline |
| Fuse | `harmonize/model.py` | S-NPP observed when available, then NOAA-20/21 scaled to S-NPP (covers S-NPP gaps and its eventual retirement), then the Aqua+Terra model, then the Terra-only model |
| Validate | `harmonize/validate.py` | Backcast test (train 2017 onward, predict 2013 to 2016) plus leave one year out, at cell, region-month and region-year scale |
| Calendar | `harmonize/calendar.py` | Area selection (bbox, polygon, point+radius), monthly series, median-based anomalies, ranks, summary, figures |

Two design choices worth defending to judges:

1. **No long-term climatology features.** We tried them. They pull predictions toward the
   average, which overestimates quiet years and underestimates busy ones exactly where it
   hurts (the MODIS-only years). Same-month neighbourhood activity replaced them.
2. **One reference platform, not "all VIIRS pooled".** Pooling makes the series depend on how
   many satellites happen to be flying.

## Getting real FIRMS data

1. Go to the FIRMS **Archive Download** page: https://firms.modaps.eosdis.nasa.gov/download/
   (free Earthdata login).
2. Create one request per source for your area (country, or a custom box/polygon):
   * MODIS Collection 6.1
   * VIIRS S-NPP (375 m)
   * VIIRS NOAA-20 (375 m)
   * VIIRS NOAA-21 (375 m)
   Date range from 2000-11-01 to today, format CSV.
3. You get an email with a link for each. The archive (standard processing) lags a few months
   behind; the download also includes NRT files for the most recent period. Keep both.
4. Unzip everything into one folder, e.g. `data/firms_punjab/`. File names do not matter.

## Running

```bash
pip install -r requirements.txt

# Synthetic test data (generated locally, no download needed)
python run_pipeline.py --demo --out outputs/demo_punjab

# Real data
python run_pipeline.py --input data/firms_punjab --region punjab_pk --out outputs/punjab
python run_pipeline.py --input data/firms_ar --bbox -60.9,-34.4,-58.3,-32.6 --out outputs/parana

# Any area inside a finished run (what the web app will call)
python make_calendar.py --run outputs/punjab --point 74.35,31.55 --radius 40 --name "Lahore 40 km"
python make_calendar.py --run outputs/punjab --polygon "73,30 74,30 74,31 73,31" --start 2003-01
```

A full Punjab run takes about 5 minutes on a laptop, most of it the validation folds
(skip them with `--skip-validation` once you trust the setup).

## Outputs (per run folder)

| File | Use |
|---|---|
| `harmonized_cell_month.parquet` / `.csv.gz` | The harmonized dataset: cell, month, harmonized count, source used, raw counts per platform. **This is the web app's input** |
| `detections_clean.parquet` | Filtered raw detections, for the "download hotspots in my area" CSV |
| `calendar_region.csv`, `calendar_counts.png`, `calendar_anomaly.png` | Region calendar, median-based anomaly, rank of each month among the same month in other years |
| `annual_totals.csv`, `break_check.png` | Raw pooled vs Aqua only vs harmonized. The "money slide" |
| `validation_metrics.csv`, `validation_monthly.png` | Leave one year out results |
| `REPORT.md` | Everything above in one page |
| `models.joblib` | Fitted models |

## Real results (NASA FIRMS, November 2000 to 11 November 2026)

Full reports and charts per region are in `results/<region>/` (`REPORT.md`, `break_check.png`,
`calendar_counts.png`, `calendar_anomaly.png`, `validation_monthly.png` and the CSV tables).

| Region | Grid | Hotspots after filtering | Backcast monthly r | Backcast bias | Single backcast years |
|---|---|---|---|---|---|
| Pakistan | 0.1 degrees | 1,545,904 | 0.972 | -5.1% | -9% to +1% |
| India (Northwest) | 0.1 degrees | 3,026,423 | 0.988 | -3.7% | -10% to +4% |
| Argentina | 0.25 degrees | 6,277,174 | 0.995 | -2.5% | -5% to +2% |

The backcast test trains on 2017 onward and predicts 2013 to 2016, the same backward direction used
to rebuild 2000 to 2011. In every region the 2012 jump in the raw pooled counts (6.7x, 7.1x, 3.1x)
disappears in the harmonized series.

### Model notes

* The transfer model is gradient boosting on log(1 + count), calibrated per calendar month so that
  training totals match observed totals. A Poisson-loss version was tried first: it extrapolated
  exponentially on Argentina (cells with hundreds of millions of hotspots), so it was replaced.
* `run_pipeline.py` compares the model with a simple shrunken ratio method on the backcast test and
  keeps the better one, scoring error and bias together. All three regions chose gradient boosting.
* Big countries: use `--grid 0.25` and `--loyo-folds 5` to keep runs fast. Keep each country's FIRMS
  files in their own folder, because a region box can overlap a neighbouring country.

### Regional caveats

* **Northwest India:** detected burning has dropped sharply since 2021. Studies report farmers
  shifting burning to after the afternoon satellite passes, so recent years likely undercount fires.
* **Pakistan:** Aqua's orbit drift in recent years changes how MODIS relates to VIIRS; the backcast
  test, which matters for the early years, is not affected.
* **All regions:** November 2000 to June 2002 rely on Terra alone and are the least certain months.

## Synthetic test results

The synthetic generator (`harmonize/synthetic.py`) simulates a Punjab-like region from 2000 to
2026 with wheat (Apr to May) and rice (Oct to Nov) residue burning, a northern summer forest
season, a rising trend, persistent industrial sources, a simulated S-NPP outage (Aug 2022), and
per satellite overpass times, detection thresholds and pixel splitting. Because the true number
of fires is known, we can check whether harmonization actually removes the sensor breaks.

**Detections per true fire, indexed to 2003 to 2011 = 1:**

| Series | 2003 to 2011 | 2013 to 2023 | Change |
|---|---|---|---|
| All satellites pooled (raw) | 1.00 | 4.75 | +375% |
| Aqua MODIS only (raw) | 1.00 | 0.98 | -2% |
| **Harmonized** | 1.00 | 0.98 | **-2%** |

Raw pooled counts jump 3.6x in 2012, 5.7x in 2018 and 8.1x in 2024 while true fire activity
does not. The harmonized series stays flat across all three transitions, while keeping VIIRS
detail (about 3.5x more hotspots than Aqua alone).

**Leave one year out (12 held-out years, 2013 to 2025):**

| Model | Region-month r | Region-month MAE | Bias |
|---|---|---|---|
| Gradient boosting, Aqua + Terra | 0.999 | 62 hotspots | -0.4% |
| Gradient boosting, Terra only | 0.996 | 136 hotspots | -0.9% |
| Ratio baseline | 0.994 | 245 hotspots | -0.5% |

The pipeline also found the simulated S-NPP gap on its own and filled it from NOAA-20.

## Known limits and next steps

* **Synthetic data is not proof.** It checks that the code works and that the method removes
  breaks it should remove. Quote the real results above, not these.
* **Land cover.** On real data, add a per cell MODIS land cover class (MCD12Q1, e.g. from Earth
  Engine) as a `landcover` column and set `extra_features=("landcover",)` in `config.py`. It
  describes the fire regime (crop residue vs forest vs grass) without leaking long-term levels.
* **Terra-only months** (Nov 2000 to Jun 2002) are the least certain part of the record. The
  calendar marks reconstructed years with `*`.
* **Static source mask** uses activity in 9+ calendar months and 30%+ of all months over 3+ years.
  Check the masked cells on a map for your region; brick kiln belts may need a lower threshold.
* **Grid size.** 0.1 degrees (about 11 km) balances map detail and model stability. Coarser
  grids (`--grid 0.25`) make the transfer more stable in sparse regions.
* Part 2, the web app, lives in `../webapp/`. `build_webapp_data.py` turns a run folder into its data files.
