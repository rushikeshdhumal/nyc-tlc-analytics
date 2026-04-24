# ADR-007: Difference-in-Differences OLS for Congestion Pricing Impact Estimation

| Field       | Value                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Date**    | 2026-04-23                   |
| **Author**  | Rushikesh Dhumal             |

---

## Context

NYC's Central Business District (CBD) Congestion Pricing policy took effect on
2025-01-05, charging a surcharge for vehicles entering Manhattan south of 60th
Street. The TLC pipeline captures taxi trips before and after this date across
all boroughs, providing a natural experiment to estimate the causal effect on
yellow taxi demand and revenue.

Two analytical questions drive this work:

1. Did congestion pricing reduce yellow taxi pickups in the Manhattan CBD?
2. Did it reduce daily revenue for yellow taxi drivers operating in the CBD?

These are **causal** questions, not correlation questions. A simple pre/post
comparison of Manhattan trip counts is confounded by seasonality, economic
trends, and any other shocks that happened to occur around January 2025.
A credible causal estimate requires isolating the congestion pricing treatment
from these confounders.

---

## Decision

Estimate the average treatment effect on the treated (ATT) using a
**Two-Way Fixed Effects (TWFE) Difference-in-Differences (DiD) OLS** regression.

The model is re-run monthly as the post-treatment window grows, so the β₃
estimate stabilises and reveals whether the effect persists, fades, or
accelerates over time (an **incremental DiD** design).

---

## Design

### Identification strategy

Standard DiD with TWFE for panel data:

```
Y_it = α + β₁·post_t + β₃·(post_t × treated_i) + zone_FE_i + dow_FE_t + ε_it
```

| Term | Role |
|---|---|
| `Y_it` | Outcome: trip count or total revenue for zone *i* on date *t* |
| `post_t` | 1 if date ≥ 2025-01-05, else 0 |
| `treated_i` | Time-invariant indicator: 1 for Manhattan CBD Yellow Zone zones |
| `post_t × treated_i` | Interaction — the DiD estimator (**β₃**) |
| `zone_FE_i` | Zone-level dummies (absorb all time-invariant zone characteristics, including the `treated` main effect) |
| `dow_FE_t` | Day-of-week dummies (absorb weekly seasonality) |

**β₃ is the causal estimate**: the average change in the outcome for treated
zones in the post period, relative to the counterfactual trend established by
the control zones.

### Treatment and control groups

- **Treatment**: `pickup_borough = 'Manhattan' AND service_zone = 'Yellow Zone'`
  (zones inside the CBD congestion pricing cordon)
- **Control**: `pickup_borough IN ('Brooklyn', 'Queens', 'Bronx')`
  (outer-borough zones unaffected by the cordon surcharge)
- **Pre period**: 2024-01-01 → 2025-01-04
- **Post period**: 2025-01-05 → latest available Gold date

### Key modelling choices and rationale

**`treated` main effect excluded from the regressor matrix.** It is absorbed by
zone fixed effects, which already capture all time-invariant zone-level
characteristics. Including it would create perfect multicollinearity.

**Zone fixed effects implemented via dummy encoding** (`pd.get_dummies` on
`pu_location_id`, `drop_first=True`). Statsmodels OLS is used rather than a
dedicated panel library because the dataset is small enough for in-memory OLS
and because TWFE is equivalent to OLS with dummies for balanced panels of
this size.

**Two outcomes estimated independently**: `trip_count` (demand effect) and
`total_revenue` (revenue effect). Running separate regressions avoids
multicollinearity between outcomes and allows each β₃ to be independently
significant.

**Incremental post window**: each monthly re-run extends the post period by
approximately one month. This tracks how β₃ evolves as the policy matures —
an effect that converges to a stable value is more credible than one that
fluctuates wildly.

### Parallel trends assumption

The validity of DiD rests on the parallel trends assumption: in the absence of
treatment, treated and control zones would have followed the same trend. This
is plausible here because:

- 2024 pre-period data establishes a long parallel baseline (~12 months).
- Day-of-week fixed effects control for intra-week seasonality shared across
  all zones.
- Control boroughs (Brooklyn, Queens, Bronx) experienced the same macro
  economic and weather conditions as Manhattan in the post period.

A formal pre-trend test (event study) is deferred to a future iteration.

### Output schema

Results are written to `NYC_TLC_DB.ML.FCT_CONGESTION_PRICING_IMPACT` (one row
per zone × period × run_date) by
`ml/models/causal_inference/congestion_pricing_did.py`.

Presentation views for Superset are defined in
`infra/scripts/congestion_pricing_views.sql`:
- `ML.V_CONGESTION_DID_BETA_SERIES` — β₃ time series per run date
- `ML.V_CONGESTION_BOROUGH_SUMMARY` — borough × period aggregates per run date

---

## Options Considered

| | TWFE DiD OLS (chosen) | Synthetic Control | Regression Discontinuity |
|---|---|---|---|
| **Causal validity** | Valid under parallel trends | Valid under donor pool assumptions | Valid at bandwidth around cutoff |
| **Data requirements** | Panel: many zones, many dates | Need a well-matched "synthetic" treated unit | Needs granular data near 2025-01-05 |
| **Multiple zones** | Handles naturally via zone FEs | Designed for one treated unit | Handles naturally |
| **Interpretability** | β₃ is a single, interpretable number | Requires visualising pre-fit weights | LATE around cutoff only |
| **Implementation** | Statsmodels OLS, ~20 lines | Complex donor selection, iterative optimisation | Requires bandwidth selection |

**Synthetic Control** was considered for its robustness to parallel trends
violations but was excluded because it is designed for a single aggregate
treated unit (e.g., one city), not a heterogeneous panel of 200+ taxi zones.

**Regression Discontinuity** would only estimate a Local Average Treatment
Effect (LATE) immediately around the policy start date, discarding months of
post-treatment data. The goal here is the full ATT over the growing post window,
not a local estimate at the boundary.

---

## Consequences

**Positive**
- A production-grade causal estimate of congestion pricing impact is updated
  monthly without any manual intervention after the `ingest_nyc_taxi_raw` DAG
  completes.
- MLflow logs all run parameters and estimates, providing full reproducibility
  and a time series of how β₃ evolves.
- Superset dashboard (see `viz/superset/congestion_pricing_impact__v1.0.0__`) 
  makes the findings accessible to non-technical stakeholders.

**Limitations and trade-offs**
- **Parallel trends is assumed, not formally tested.** A pre-trend event study
  plot would strengthen credibility and should be added in a future iteration.
- **Spillover effects are not modelled.** If congestion pricing diverted trips
  to outer boroughs, the control group is partially treated, and β₃ would
  underestimate the true effect (attenuation bias). The `avg_congestion_fees`
  column in the output table can be used to check for unexpected post-period
  fee activity in control zones.
- **Heterogeneous treatment effects** across zones are not estimated. The β₃
  estimate is an average across all treated zones. Zone-level heterogeneity
  analysis is deferred to a future iteration.
- **Standard errors are not clustered.** Clustered standard errors at the zone
  or borough level would give more conservative (and correct) inference. Deferred
  to future iteration.

---

## Files Changed

| File | Change |
|------|--------|
| `ml/models/causal_inference/congestion_pricing_did.py` | New TWFE DiD OLS training script |
| `ml/utils/snowflake_io.py` | Added `insert_congestion_impact_rows()` |
| `infra/scripts/ml_setup.sql` | Added `FCT_CONGESTION_PRICING_IMPACT` DDL |
| `infra/scripts/congestion_pricing_views.sql` | New Superset presentation views |
| `orchestration/dags/congestion_pricing_analysis.py` | New Airflow DAG (`schedule=None`) |
| `orchestration/dags/ingest_nyc_taxi_raw.py` | Added `trigger_congestion` in parallel with `trigger_retrain` |
| `viz/superset/congestion_pricing_impact__v1.0.0__2026-04-23.notes.md` | Superset chart definitions |
