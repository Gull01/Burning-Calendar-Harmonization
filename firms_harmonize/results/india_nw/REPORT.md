# Harmonization run report

Input: NASA FIRMS archive and NRT downloads for india  
Region: india_nw (73.8, 27.4, 80.6, 32.8)  
Grid: 0.1 degrees

## Filtering

- input: 3,442,846
- dropped_non_vegetation_type: 31,988
- dropped_low_confidence: 383,330
- static_cells_found: 4
- dropped_static_sources: 1,105
- output: 3,026,423

## Leave one year out validation

| model          | scale        |      n |   pearson_r |   pearson_r_log1p |       mae |   bias_pct |
|:---------------|:-------------|-------:|------------:|------------------:|----------:|-----------:|
| pred_gbm_aqua  | cell-month   | 172680 |       0.935 |             0.868 |     1.418 |       0.28 |
| pred_gbm_aqua  | region-month |     60 |       0.993 |             0.986 |   662.493 |       0.28 |
| pred_gbm_aqua  | region-year  |      5 |       0.999 |             1     |  3013.01  |       0.28 |
| pred_gbm_terra | cell-month   | 172680 |       0.82  |             0.779 |     2.061 |      -9.22 |
| pred_gbm_terra | region-month |     60 |       0.963 |             0.977 |  1676.26  |      -9.22 |
| pred_gbm_terra | region-year  |      5 |       0.962 |             0.963 | 11032.6   |      -9.22 |
| pred_ratio     | cell-month   | 172680 |       0.913 |             0.85  |     1.624 |      -1.34 |
| pred_ratio     | region-month |     60 |       0.974 |             0.977 |  1703.27  |      -1.34 |
| pred_ratio     | region-year  |      5 |       0.996 |             0.998 |  7515.39  |      -1.34 |

### Annual totals for each held-out year (gradient boosting)

|   year |   observed |   predicted |   bias_pct |
|-------:|-----------:|------------:|-----------:|
|   2013 |     103091 |      103488 |          0 |
|   2016 |     160906 |      154085 |         -4 |
|   2019 |      96892 |       98010 |          1 |
|   2022 |      96188 |       99325 |          3 |
|   2025 |      44060 |       47651 |          8 |

Model used to rebuild pre-2012 years: **gbm**

## Backcast test

Trained on 2017 to 2026, predicted 2013 to 2016 (the same backward direction used to rebuild 2000 to 2011).

| model | region-month r | MAE | bias % |
|---|---|---|---|
| pred_gbm_aqua | 0.988 | 1190.64 | -3.65 |
| pred_ratio | 0.984 | 1950.839 | -11.2 |

|   year |   observed |   predicted_gbm |   bias_pct_gbm |   predicted_ratio |   bias_pct_ratio |
|-------:|-----------:|----------------:|---------------:|------------------:|-----------------:|
|   2013 |     103091 |          106717 |              4 |            100346 |               -3 |
|   2014 |     123814 |          119267 |             -4 |            108869 |              -12 |
|   2015 |     105214 |           95232 |            -10 |             92705 |              -12 |
|   2016 |     160906 |          153835 |             -4 |            135874 |              -16 |

## Sources used in the harmonized series (cell-months)

| source                 |   cell_months |
|:-----------------------|--------------:|
| MODIS_Aqua+Terra_model |        328092 |
| MODIS_Terra_model      |         60438 |
| VIIRS_NOAA20_scaled    |          2878 |
| VIIRS_SNPP_observed    |        509406 |

## Region summary

```json
{
  "latest_month_days_covered": "37%",
  "latest_month_typical_share_by_now": "72%",
  "peak_calendar_month": "Oct",
  "top_years": [
    2016,
    2021,
    2012
  ],
  "quietest_year": 2025,
  "latest_month": "2026-11",
  "latest_month_hotspots": 3060.8,
  "latest_month_median": 22799.2,
  "latest_month_anomaly_pct": -86.6,
  "latest_month_rank": "25 of 27"
}
```

