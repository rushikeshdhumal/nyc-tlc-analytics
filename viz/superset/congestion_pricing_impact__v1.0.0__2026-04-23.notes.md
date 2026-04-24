# Congestion Pricing Impact Dashboard

**Release:** v1.0.0
**Date:** 2026-04-23
**Branch:** ml/congestion-pricing

## Overview

This dashboard visualises the causal effect of NYC's CBD Congestion Pricing policy
(effective 2025-01-05) on yellow taxi trip demand and revenue. It draws from the
ML schema rather than the Gold schema because the estimates are produced by a
statistical model, not raw aggregates.

Treatment group: Manhattan Yellow Zone taxi zones  
Control group: Brooklyn, Queens, Bronx  
Method: Two-Way Fixed Effects Difference-in-Differences OLS (zone + day-of-week FEs)

## Data Sources

| Superset Dataset | Snowflake Object | Notes |
|---|---|---|
| `congestion_did_beta_series` | `NYC_TLC_DB.ML.V_CONGESTION_DID_BETA_SERIES` | One row per monthly DiD run — β₃ time series |
| `congestion_borough_summary` | `NYC_TLC_DB.ML.V_CONGESTION_BOROUGH_SUMMARY` | Borough × period aggregates per run |

Run `infra/scripts/congestion_pricing_views.sql` in Snowflake before connecting
these datasets in Superset.

## Charts

### Chart 1 — DiD Treatment Effect (β₃) Over Time

| Setting | Value |
|---|---|
| **Chart type** | Line chart |
| **Dataset** | `congestion_did_beta_series` |
| **X-axis** | `run_date` (TEMPORAL, Month grain) |
| **Metrics** | `beta_trip_count` (AVG), `beta_revenue` (AVG) |
| **Y-axis label** | "Causal Effect (β₃)" |
| **Reference line** | y = 0 (dashed, colour #888) |
| **Dual Y-axis** | Yes — left axis: trips, right axis: revenue ($) |
| **Tooltip** | Include `p_value_trip_count`, `r2_trip_count` |

**Interpretation:** Each point is the β₃ coefficient from the month's DiD run.
As the post-treatment window grows, the estimate converges to the long-run
average treatment effect on the treated (ATT). A stable, negative β₃ confirms
that congestion pricing persistently suppressed CBD taxi demand.

### Chart 2 — Pre/Post Avg Daily Trip Count by Borough

| Setting | Value |
|---|---|
| **Chart type** | Grouped bar chart |
| **Dataset** | `congestion_borough_summary` |
| **Filter** | `run_date = MAX(run_date)` (use the latest run) |
| **X-axis** | `borough` |
| **Series** | `period` (pre / post) |
| **Metric** | `total_avg_daily_trips` (SUM) |
| **Color** | `period`: pre = #4C78A8, post = #E45756 |
| **Sort** | Descending by pre-period trips |

**Interpretation:** Side-by-side pre/post bars make the demand shift visible per
borough. Manhattan (treated) should show a steeper drop pre → post than the
control boroughs. Any post-period increase in control boroughs may signal
trip diversion.

### Chart 3 (optional) — Model Fit Summary Table

| Setting | Value |
|---|---|
| **Chart type** | Table |
| **Dataset** | `congestion_did_beta_series` |
| **Columns** | `run_date`, `beta_trip_count`, `p_value_trip_count`, `r2_trip_count`, `beta_revenue`, `p_value_revenue`, `r2_revenue` |
| **Sort** | `run_date` DESC |

Shows full model diagnostics per run. Useful for confirming statistical
significance (p < 0.05) and goodness-of-fit across months.

## Dashboard Layout (suggested)

```
┌────────────────────────────────────────────────────────────┐
│  KPI: β₃ trips (latest)  │  KPI: p-value  │  KPI: R²       │
├────────────────────────────────────────────────────────────┤
│  Chart 1: β₃ Over Time (full width, Line)                  │
├────────────────────────────────────────────────────────────┤
│  Chart 2: Borough Pre/Post (left)  │  Chart 3: Table (right)│
└────────────────────────────────────────────────────────────┘
```

## KPI Cards (Big Number charts)

| KPI | Dataset | Metric | Filter |
|---|---|---|---|
| β₃ (trips, latest) | `congestion_did_beta_series` | `beta_trip_count` (AVG) | `run_date = MAX` |
| p-value (trips) | `congestion_did_beta_series` | `p_value_trip_count` (AVG) | `run_date = MAX` |
| R² (trip model) | `congestion_did_beta_series` | `r2_trip_count` (AVG) | `run_date = MAX` |

## Required Setup

1. Run `infra/scripts/congestion_pricing_views.sql` as DE_ROLE.
2. In Superset, add two new virtual datasets pointing to the two views above.
3. Set the Snowflake connection to use ANALYST_ROLE (read-only).
4. Build the three charts and assemble the dashboard.
5. Export the dashboard as a ZIP via `Dashboards > Export` and save to
   `viz/superset/congestion_pricing_impact__v1.0.0__<export-date>.zip`.

## Maintenance

- Re-running `congestion_pricing_analysis` DAG appends a new `_run_date` row.
  Chart 1 automatically picks up the new point; Charts 2 and 3 should have a
  `run_date` filter set to `MAX` so they always show the latest run.
- Bump the version for any structural chart or dataset changes.
