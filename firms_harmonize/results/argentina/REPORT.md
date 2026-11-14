# Harmonization run report

Input: NASA FIRMS archive and NRT downloads for argentina  
Region: argentina (-73.6, -55.1, -53.6, -21.7)  
Grid: 0.25 degrees

## Filtering

- input: 7,075,667
- dropped_non_vegetation_type: 256,131
- dropped_low_confidence: 540,055
- static_cells_found: 8
- dropped_static_sources: 2,307
- output: 6,277,174

## Leave one year out validation

| model          | scale        |      n |   pearson_r |   pearson_r_log1p |       mae |   bias_pct |
|:---------------|:-------------|-------:|------------:|------------------:|----------:|-----------:|
| pred_gbm_aqua  | cell-month   | 258000 |       0.909 |             0.874 |     1.77  |      -0.68 |
| pred_gbm_aqua  | region-month |     60 |       0.988 |             0.993 |  1425.72  |      -0.68 |
| pred_gbm_aqua  | region-year  |      5 |       0.994 |             0.993 |  5384.55  |      -0.68 |
| pred_gbm_terra | cell-month   | 258000 |       0.849 |             0.773 |     2.593 |      -4.55 |
| pred_gbm_terra | region-month |     60 |       0.97  |             0.971 |  2577.38  |      -4.55 |
| pred_gbm_terra | region-year  |      5 |       0.971 |             0.966 | 12112.9   |      -4.55 |
| pred_ratio     | cell-month   | 258000 |       0.916 |             0.861 |     1.995 |      -2.58 |
| pred_ratio     | region-month |     60 |       0.963 |             0.975 |  2543.58  |      -2.58 |
| pred_ratio     | region-year  |      5 |       0.994 |             0.991 | 14750.5   |      -2.58 |

### Annual totals for each held-out year (gradient boosting)

|   year |   observed |   predicted |   bias_pct |
|-------:|-----------:|------------:|-----------:|
|   2013 |     210289 |      198642 |         -6 |
|   2016 |     162837 |      169129 |          4 |
|   2019 |     143298 |      143806 |          0 |
|   2022 |     271326 |      266323 |         -2 |
|   2025 |     149001 |      152474 |          2 |

Model used to rebuild pre-2012 years: **gbm**

## Backcast test

Trained on 2017 to 2026, predicted 2013 to 2016 (the same backward direction used to rebuild 2000 to 2011).

| model | region-month r | MAE | bias % |
|---|---|---|---|
| pred_gbm_aqua | 0.995 | 930.177 | -2.45 |
| pred_ratio | 0.985 | 1433.835 | -1.09 |

|   year |   observed |   predicted_gbm |   bias_pct_gbm |   predicted_ratio |   bias_pct_ratio |
|-------:|-----------:|----------------:|---------------:|------------------:|-----------------:|
|   2013 |     210289 |          199675 |             -5 |            194602 |               -8 |
|   2014 |     108424 |          107783 |             -1 |            109771 |                1 |
|   2015 |     136330 |          129232 |             -5 |            140022 |                3 |
|   2016 |     162837 |          166058 |              2 |            166774 |                2 |

## Sources used in the harmonized series (cell-months)

| source                 |   cell_months |
|:-----------------------|--------------:|
| MODIS_Aqua+Terra_model |        490200 |
| MODIS_Terra_model      |         90300 |
| VIIRS_NOAA20_scaled    |          4300 |
| VIIRS_SNPP_observed    |        761100 |

## Region summary

```json
{
  "latest_month_days_covered": "37%",
  "latest_month_typical_share_by_now": "35%",
  "peak_calendar_month": "Aug",
  "top_years": [
    2020,
    2003,
    2008
  ],
  "quietest_year": 2014,
  "latest_month": "2026-11",
  "latest_month_hotspots": 4033.3,
  "latest_month_median": 3622.6,
  "latest_month_anomaly_pct": 11.3,
  "latest_month_rank": "13 of 27"
}
```

