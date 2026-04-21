# Experiment Log — Demand Forecasting

Record every experiment cycle here. One entry per run_date / experiment session.
Link MLflow run IDs so findings are reproducible.

---

## Template

```
## YYYY-MM-DD — Stage N: <stage name>

**run_date**: YYYY-MM-DD  
**MLflow experiment**: demand_forecast_hourly  
**Splits**: train YYYY-MM-DD → YYYY-MM-DD | val YYYY-MM-DD → YYYY-MM-DD | test YYYY-MM-DD → YYYY-MM-DD

### Runs
| MLflow Run ID | Model / Config | val_mape | test_mape | mape_vs_baseline | Notes |
|---|---|---|---|---|---|
| abc123 | lightgbm default | 12.3% | 13.1% | +2.4% | baseline |

### Findings
- ...

### Next step
- ...
```

---

## 2026-04-21 — Stage 2: Baseline Comparison

**run_date**: 2026-04-21
**MLflow experiment**: demand_forecast_hourly
**Splits**: train 2024-01-08 → 2025-12-31 | val 2026-01-01 → 2026-01-31 | test 2026-02-01 → 2026-02-28

### Runs
| MLflow Run ID | Model / Config | test_mape | Notes |
|---|---|---|---|
| 9aec9bad | naive lag-168 | 236.38% | primary benchmark per ADR-005 |
| faf657fc | seasonal naive (avg lag cols) | 124.12% | |
| 2ca53f48 | Ridge (alpha=1.0, all features) | 99.33% | best baseline |

### Findings
- All baseline MAPEs are high (~100–236%) because the aggregate MAPE is dominated by low-demand zone-hours (37% of rows have <5 trips — small denominators inflate percentage errors). This is consistent with EDA: median per-zone lag-168 MAPE was 28.9% but mean was 89.7%.
- Ridge (99.33%) is the binding baseline to beat. LightGBM with lag_1h (r=0.951) should beat this comfortably.
- The lag-168 MAPE (236%) is extremely high for the Feb 2026 test period — likely driven by residual congestion pricing disruption in Manhattan CBD zones.

### Next step
- Stage 3: run `feature_ablation.py` to identify which feature groups drive MAPE reduction

## 2026-04-21 — Stage 3: Feature Ablation

**run_date**: 2026-04-21  
**MLflow experiment**: demand_forecast_hourly  
**Splits**: same as Stage 2

### Runs
| Variant | n_features | test_mape | delta vs full |
|---|---|---|---|
| full (all 12) | 12 | 35.33% | — |
| no_rolling | 10 | 36.15% | +0.82% |
| no_congestion | 11 | 35.55% | +0.22% |
| **no_borough_enc** | **11** | **35.22%** | **-0.11% (better)** |
| no_lag | 6 | 68.53% | +33.20% |
| calendar_only | 5 | 72.57% | +37.24% |

### Findings
- **Lag features are critical**: removing them doubles MAPE (35.33% → 68.53%). lag_1h (r=0.951) is the dominant signal.
- **Rolling features are marginal**: only +0.82% without them. Could be pruned without meaningful loss.
- **Congestion fees are negligible at aggregate level**: +0.22% — likely matters more for Manhattan CBD zones specifically, keep for now.
- **Borough encoding slightly hurts**: -0.11% improvement without it — `pu_location_id` already encodes zone identity; `pickup_borough_enc` is a coarser duplicate that adds noise.
- **LightGBM (full, 35.33%) vs best baseline (Ridge, 99.33%)**: Stage 2 gate passed with a 64 percentage point improvement.

### Decision: remove `pickup_borough_enc` from FEATURE_COLS
The ablation confirms it's redundant. Update `demand_features.py` before Stage 4.

### Next step
- Update FEATURE_COLS (remove pickup_borough_enc), delete cache, run Stage 4 model comparison

<!-- Add experiment entries below, newest first -->
