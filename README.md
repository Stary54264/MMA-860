# MMA-860: Predicting Hourly NYC Yellow Taxi Demand

Predict hourly taxi pickups per NYC taxi zone using time of day, day of week, month, historic demand, and external factors (weather, daylight, holidays, events, rideshare activity, airport volume, zone demographics). See `MMA860 Project Proposal.docx` for the full proposal.

## Data

- **Source:** [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page), Yellow Taxi, Jan–Dec 2025 (monthly Parquet files)
- **Combined file:** `combined_data_final.csv` (48,722,602 trips, ~4.9 GB). Not tracked in git because of its size; download and combine locally.
- **Key columns:** `tpep_pickup_datetime`, `PULocationID`, aggregated to trip counts per zone per hour.

## Planned Analysis

1. Clean: missing pickup locations, duplicates, out-of-range timestamps
2. Aggregate to hourly pickups by zone; join external datasets
3. Chronological train / validation / test split
4. Multiple linear regression models with different predictor sets, compared using F-tests and checked for collinearity
5. Residual plots and heteroskedasticity checks
6. Forecast accuracy: MAE, RMSE
7. Frisch–Waugh–Lovell: effect of weather on demand after removing hour, day-of-week, and month seasonality
