# ML Feature Contracts

Defines the canonical feature sets for each ML model, the source Gold columns
they map to, and the leakage boundary (what data is available at prediction time).

---

## Leakage Boundary Rule

The target variable for a prediction at time `T` must never appear as a feature.
All features must be constructed from data with timestamps **strictly before** `T`.

- **Demand forecasting** (predict `trip_count` for hour `H`): features may use
  any data up to and including hour `H-1`. Same-hour metrics from the same zone
  are forbidden as features.
- **Anomaly detection** (score day `D`): uses rolling statistics over the 30
  days ending at `D-1`. Same-day values are forbidden as inputs to the z-score
  baseline.
- **Causal inference** (DiD): treatment assignment (Manhattan CBD) is fixed and
  known at all times. Pre/post period split is at 2025-01-05 (CBD pricing
  effective date). No leakage risk, but test/control group assignment must be
  frozen before model fit.

---

## Model 1: Demand Forecasting (`demand_forecast_hourly`)

### Source table
`NYC_TLC_DB.GOLD.fct_revenue_per_zone_hourly`

### Target variable
`trip_count` — number of trips in a given `(pickup_hour, pu_location_id)` bucket.

### Feature matrix

| Feature | Source column | Type | Notes |
|---|---|---|---|
| `hour_of_day` | `hour_of_day` | Calendar | 0–23 |
| `day_of_week_num` | derived from `pickup_hour` | Calendar | 0=Mon … 6=Sun |
| `month` | derived from `pickup_hour` | Calendar | 1–12 |
| `is_weekend` | derived from `day_of_week` | Calendar | 1 if Sat/Sun |
| `lag_1h_trip_count` | `trip_count` at `pickup_hour - 1` | Lag | Same zone |
| `lag_24h_trip_count` | `trip_count` at `pickup_hour - 24` | Lag | Same zone, same hour yesterday |
| `lag_168h_trip_count` | `trip_count` at `pickup_hour - 168` | Lag | Same zone, same hour last week — also the naive baseline |
| `rolling_24h_avg_trip_count` | rolling mean over last 24 hours | Rolling | Same zone |
| `rolling_168h_avg_trip_count` | rolling mean over last 168 hours | Rolling | Same zone |
| `pu_location_id` | `pu_location_id` | Dimension | Encoded as integer |
| `pickup_borough` | `pickup_borough` | Dimension | Label-encoded |
| `total_congestion_fees` | `total_congestion_fees` at `lag_168h` | Revenue signal | Lagged to avoid leakage |

### Forbidden features (leakage)
- `total_revenue`, `revenue_per_trip`, `total_fare` at time `H` — these are
  outcomes of the same trips we are predicting.
- `avg_tip_pct`, `credit_card_trip_pct` at time `H` — same reason.
- Any same-hour metric from the target zone.

### Naive baseline
`lag_168h_trip_count` — last week's same-hour value. LightGBM model must beat
this on MAPE on the holdout set before promotion to Production in MLflow.

### Train / validation / test split
Dataset spans Jan 2024 – Jan 2026 (25 months). Splits are fixed dates, not relative:
- **Train**: 2024-01-01 to 2025-10-31 (22 months)
- **Validation**: 2025-11-01 to 2025-12-31 (2 months — used for hyperparameter tuning)
- **Test / holdout**: 2026-01-01 to 2026-01-31 (1 month — never used during training or tuning)
- Never shuffle. Always sort by `pickup_hour` ascending before splitting.
- When new monthly data arrives, extend train end by one month and roll validation/test forward.

---

## Model 2: Anomaly Detection (`anomaly_detection_daily`)

### Source table
`NYC_TLC_DB.GOLD.fct_revenue_daily`

### What is flagged
A `(pickup_date, pu_location_id)` row is flagged as anomalous when its
`trip_count` z-score exceeds 3.0 on a rolling 30-day window ending at `D-1`.

### Feature / statistic set

| Statistic | Derivation | Notes |
|---|---|---|
| `rolling_30d_mean` | mean of `trip_count` over days `D-30` to `D-1` | Per zone |
| `rolling_30d_std` | std dev of `trip_count` over days `D-30` to `D-1` | Per zone |
| `z_score` | `(trip_count - rolling_30d_mean) / rolling_30d_std` | Flagged if > 3.0 |
| `revenue_z_score` | same calculation on `total_revenue` | Secondary signal |

### Output
Written to `NYC_TLC_DB.ML.fct_anomalies`:
- `anomaly_date`, `pu_location_id`, `pickup_borough`, `trip_count`, `z_score`,
  `revenue_z_score`, `is_anomaly` (boolean), `_scored_at`.

---

## Model 3: Congestion Pricing Impact (`congestion_pricing_did`)

### Source table
`NYC_TLC_DB.GOLD.fct_revenue_daily`

### Treatment assignment (frozen)
- **Treatment group**: zones where `pickup_borough = 'Manhattan'`
  and `service_zone = 'Yellow Zone'` (CBD zones affected by congestion pricing)
- **Control group**: `pickup_borough IN ('Brooklyn', 'Queens', 'Bronx')`
  (outer borough zones, unaffected)
- **Pre period**: 2024-01-01 to 2025-01-04 (full year before pricing effective date)
- **Post period**: 2025-01-05 onward (CBD pricing active)

### Target metrics
- `trip_count` — demand impact
- `total_revenue` — revenue impact
- `total_congestion_fees` — direct surcharge pass-through

### DiD specification
`Y = α + β₁·post + β₂·treated + β₃·(post × treated) + ε`

`β₃` is the causal estimate of congestion pricing effect. Controls include
`day_of_week` and `pu_location_id` fixed effects.

### Output
Written to `NYC_TLC_DB.ML.fct_congestion_pricing_impact`:
- `pu_location_id`, `pickup_borough`, `period` (pre/post), `treated`,
  `avg_trip_count`, `avg_revenue`, `did_estimate`, `p_value`, `_run_date`.
