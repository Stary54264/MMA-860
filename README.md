# MMA-860: Predicting Hourly NYC Yellow Taxi Demand

Predict hourly taxi pickups per NYC taxi zone using time of day, day of week, month, historic demand, and external factors (weather, daylight, holidays, events, rideshare activity, airport volume, zone demographics). See `MMA860 Project Proposal.docx` for the full proposal.

## Data

- **Source:** [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page), Yellow Taxi, Jan–Dec 2025 (monthly Parquet files)
- **Combined file:** `combined_data_final.csv` (48,722,602 trips, ~4.9 GB). Not tracked in git because of its size; download and combine locally.
- **Key columns:** `tpep_pickup_datetime`, `PULocationID`, aggregated to trip counts per zone per hour.

## Cleaning

```bash
pip install duckdb
python clean_data.py   # ~1 min; reads combined_data_final.csv, writes to data/
```

- `data/trips_clean.parquet`: valid trips, all original columns (47.5M rows; 2.5% of raw rows removed)
- `data/hourly_zone_demand.parquet`: the regression dataset with `PULocationID`, `pickup_hour`, `pickups`, `log_pickups` = ln(1 + pickups). Every zone × hour is present (zero-pickup hours filled with 0) for zones averaging ≥ 1 pickup/hour (156 zones, 99.2% of trips; change with `--min-mean-pickups`). The repeated fall-back hour (2025-11-02 01:00) is dropped.

What was removed or kept, and why, is documented at the top of `clean_data.py`.

## Planned Analysis

1. Clean: missing pickup locations, duplicates, out-of-range timestamps
2. Aggregate to hourly pickups by zone; join external datasets
3. Chronological train / validation / test split
4. Multiple linear regression models with different predictor sets, compared using F-tests and checked for collinearity
5. Residual plots and heteroskedasticity checks
6. Forecast accuracy: MAE, RMSE
7. Frisch–Waugh–Lovell: effect of weather on demand after removing hour, day-of-week, and month seasonality
