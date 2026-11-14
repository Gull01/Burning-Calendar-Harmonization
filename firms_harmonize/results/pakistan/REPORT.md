# Harmonization run report

Input: NASA FIRMS archive and NRT downloads for pakistan  
Region: pakistan (60.8, 23.6, 77.9, 37.1)  
Grid: 0.1 degrees

## Filtering

- input: 1,883,152
- dropped_non_vegetation_type: 106,273
- dropped_low_confidence: 229,536
- static_cells_found: 3
- dropped_static_sources: 1,439
- output: 1,545,904

## Leave one year out validation

| model          | scale        |      n |   pearson_r |   pearson_r_log1p |      mae |   bias_pct |
|:---------------|:-------------|-------:|------------:|------------------:|---------:|-----------:|
| pred_gbm_aqua  | cell-month   | 872976 |       0.809 |             0.743 |    0.609 |      -1.21 |
| pred_gbm_aqua  | region-month |    156 |       0.977 |             0.976 |  428.405 |      -1.21 |
| pred_gbm_aqua  | region-year  |     13 |       0.94  |             0.947 | 1714.99  |      -1.21 |
| pred_gbm_terra | cell-month   | 872976 |       0.586 |             0.606 |    0.803 |      -0.89 |
| pred_gbm_terra | region-month |    156 |       0.882 |             0.939 |  862.102 |      -0.89 |
| pred_gbm_terra | region-year  |     13 |       0.362 |             0.367 | 5827.63  |      -0.89 |
| pred_ratio     | cell-month   | 872976 |       0.776 |             0.771 |    0.627 |      -0.47 |
| pred_ratio     | region-month |    156 |       0.948 |             0.966 |  647.039 |      -0.47 |
| pred_ratio     | region-year  |     13 |       0.864 |             0.862 | 3231     |      -0.47 |

### Annual totals for each held-out year (gradient boosting)

|   year |   observed |   predicted |   bias_pct |
|-------:|-----------:|------------:|-----------:|
|   2013 |      38061 |       39149 |          3 |
|   2014 |      46023 |       43146 |         -6 |
|   2015 |      38212 |       37223 |         -3 |
|   2016 |      50892 |       47053 |         -8 |
|   2017 |      50578 |       49442 |         -2 |
|   2018 |      51212 |       53561 |          5 |
|   2019 |      41666 |       42856 |          3 |
|   2020 |      43104 |       42240 |         -2 |
|   2021 |      58337 |       58340 |          0 |
|   2022 |      48392 |       51114 |          6 |
|   2023 |      43577 |       43599 |          0 |
|   2024 |      53409 |       53224 |         -0 |
|   2025 |      57790 |       52758 |         -9 |

Model used to rebuild pre-2012 years: **gbm**

## Backcast test

Trained on 2017 to 2026, predicted 2013 to 2016 (the same backward direction used to rebuild 2000 to 2011).

| model | region-month r | MAE | bias % |
|---|---|---|---|
| pred_gbm_aqua | 0.972 | 458.577 | -5.1 |
| pred_ratio | 0.957 | 708.762 | 0.09 |

|   year |   observed |   predicted_gbm |   bias_pct_gbm |   predicted_ratio |   bias_pct_ratio |
|-------:|-----------:|----------------:|---------------:|------------------:|-----------------:|
|   2013 |      38061 |           38411 |              1 |             42748 |               12 |
|   2014 |      46023 |           43041 |             -6 |             44056 |               -4 |
|   2015 |      38212 |           36757 |             -4 |             39944 |                4 |
|   2016 |      50892 |           46151 |             -9 |             46589 |               -8 |

## Sources used in the harmonized series (cell-months)

| source                 |   cell_months |
|:-----------------------|--------------:|
| MODIS_Aqua+Terra_model |        637944 |
| MODIS_Terra_model      |        117516 |
| VIIRS_NOAA20_scaled    |          5596 |
| VIIRS_SNPP_observed    |        990492 |

## Region summary

```json
{
  "latest_month_days_covered": "37%",
  "latest_month_typical_share_by_now": "40%",
  "peak_calendar_month": "May",
  "top_years": [
    2021,
    2025,
    2024
  ],
  "quietest_year": 2006,
  "latest_month": "2026-11",
  "latest_month_hotspots": 4692.7,
  "latest_month_median": 2686.0,
  "latest_month_anomaly_pct": 74.7,
  "latest_month_rank": "2 of 27"
}
```

