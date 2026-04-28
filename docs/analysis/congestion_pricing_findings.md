# Congestion Pricing Impact — DiD Findings

**Model run date:** 2026-04-24
**Method:** Two-Way Fixed Effects Difference-in-Differences OLS
**Treatment:** NYC Central Business District Congestion Pricing, effective 2025-01-05
**Status:** Single-run baseline. Monthly re-runs will accumulate as new TLC data arrives.

---

## Executive Summary

NYC's congestion pricing policy measurably reduced yellow taxi demand in Manhattan.
The raw observed drop is approximately 4,100 fewer average daily trips post-policy.
After controlling for zone and day-of-week fixed effects and netting out the trend
shared across control boroughs, the model attributes ~75 trips/day to the policy
specifically. The revenue impact follows the same direction: ~$1,172/day in
policy-attributable revenue loss. Both estimates are statistically significant at
any conventional threshold.

---

## Pre/Post Borough Summary

Data source: `NYC_TLC_DB.ML.V_CONGESTION_BOROUGH_SUMMARY`

| Borough | Treated | Pre avg daily trips | Post avg daily trips | Raw change | Pre avg daily revenue | Post avg daily revenue | Raw change |
|---|---|---|---|---|---|---|---|
| Manhattan | Yes | 81,849 | 77,730 | **−4,119 (−5.0%)** | $1,957,891 | $1,883,409 | −$74,482 (−3.8%) |
| Queens | No | 8,827 | 8,415 | −412 (−4.7%) | $670,293 | $643,864 | −$26,429 (−3.9%) |
| Brooklyn | No | 351 | 382 | +31 (+8.7%) | $11,857 | $13,064 | +$1,207 (+10.2%) |
| Bronx | No | 63 | 65 | +2 (+3.3%) | $2,441 | $2,492 | +$51 (+2.1%) |

### What the raw numbers show

**Manhattan** dropped 5% in daily trips and 3.8% in revenue. On face value this looks like a clear policy effect. But raw pre/post comparisons are unreliable — they conflate the policy effect with any concurrent trend (macroeconomic shifts, seasonality, ride-share competition) that would have affected taxi demand regardless of congestion pricing.

**Queens** fell nearly as much as Manhattan (−4.7% trips, −3.9% revenue). Queens is a control borough — it was not subject to congestion pricing — yet it declined almost identically. This is the key signal that something beyond the policy was suppressing taxi demand across the city during the post period. The DiD model's job is to net this shared trend out.

**Brooklyn and Bronx** grew modestly post-policy (+8.7% and +3.3% trips respectively). This pattern is consistent with **trip diversion**: riders who previously took a cab into the Manhattan CBD may have shifted to subway or shifted to shorter outer-borough trips, producing mild demand growth in untreated areas. This is a plausible mechanism but cannot be confirmed from this model alone.

---

## Causal Estimate (DiD β₃)

Data source: `NYC_TLC_DB.ML.V_CONGESTION_DID_BETA_SERIES`

| Coefficient | Estimate | Std interpretation |
|---|---|---|
| β₃ trip count | **−75.30 trips/day** | Policy-attributable Manhattan demand loss, net of control trend |
| β₃ revenue | **−$1,172/day** | Policy-attributable Manhattan revenue loss, net of control trend |
| p-value (trips) | 4.8 × 10⁻⁹¹ | See note below |
| p-value (revenue) | 1.9 × 10⁻¹⁸ | Highly significant |
| R² (trips) | 0.9272 | Model explains 92.7% of trip count variance |
| R² (revenue) | 0.9378 | Model explains 93.8% of revenue variance |

### Why β₃ = −75 and not −4,119

The raw drop (−4,119 trips/day in Manhattan) and the causal estimate (−75 trips/day)
look dramatically different. This is expected and correct. The fixed effects absorb the
vast majority of variation in trip counts — zone-level intercepts capture persistent
structural differences between locations, and day-of-week intercepts capture weekly
cycles. What remains after those absorb their share is a small, clean residual. β₃
measures the causal effect in that residual space, after the model has already
explained 92.7% of variance through zone and time structure.

Concretely: the −4,119 raw drop includes everything — the policy effect, Queens-style
macroeconomic headwinds, seasonal patterns, and zone-specific noise. β₃ = −75 is what
remains after all of that is stripped out.

### A note on the extreme p-value

p = 4.8 × 10⁻⁹¹ is not physically interpretable as a probability. It is an artifact
of the model fit being near-perfect (R² = 0.927): when the model explains almost all
variance, the residual standard error is very small, which mechanically deflates the
standard error of every coefficient and produces extreme t-statistics. The result is
technically valid — the estimate is genuinely significant — but the p-value should not
be read as a precision claim. In practice, report significance as p < 0.001 and move on.

---

## Limitations

### 1. Parallel trends assumption is not fully satisfied

The DiD identification strategy requires that, in the absence of treatment, the treated
unit (Manhattan) would have followed the same trend as the control group. Queens fell
nearly as sharply as Manhattan post-policy (−4.7% vs −5.0%), which weakens this
assumption. If Queens was partially affected by congestion pricing — e.g., Queens trips
that crossed into the CBD — it is a contaminated control, and using it in the control
group biases the β₃ estimate toward zero (attenuation bias). The true effect may be
larger than −75 trips/day.

A cleaner analysis would either exclude Queens or instrument for the degree of CBD
exposure per borough.

### 2. Single run — no time series of estimates yet

This analysis reflects one model run on all available data as of 2026-04-24. A robust
causal inference study would show β₃ stabilising as post-treatment observations
accumulate (an event study or rolling-window DiD). As monthly TLC data arrives and
`congestion_pricing_analysis` re-runs, the `V_CONGESTION_DID_BETA_SERIES` view will
accumulate rows. If β₃ converges to a stable value across runs, that strengthens the
causal interpretation. If it fluctuates, that signals model instability or a structural
break in the post-period.

### 3. No placebo test

A standard robustness check for DiD is a placebo test: re-run the model with a fake
treatment date (e.g., 2024-01-05, one year prior) and verify that β₃ ≈ 0. A
statistically significant β₃ on the placebo date would indicate the model is picking
up a pre-existing trend rather than a policy effect. This has not been run.

### 4. Yellow taxi is not the full demand picture

This analysis covers yellow taxi only. Ride-share (Uber, Lyft), green taxi, and FHV
are excluded — not because they are irrelevant, but because the NYC TLC dataset
available here covers yellow taxi trips only. Congestion pricing may have had a
different or offsetting effect on other modes. The −75 trips/day estimate should be
interpreted as the yellow taxi effect, not total taxi or total transit demand.

### 5. One treatment, one post period

The model treats the entire post-2025-01-05 window as a single homogeneous treatment
period. In practice, the policy effect may evolve over time — riders may initially
reduce trips sharply and then partially adjust back (habituation), or the effect may
grow as the policy becomes more entrenched. A dynamic treatment effects model
(event-study style with interaction terms for each post-month) would capture this
heterogeneity.

---

## What a More Rigorous Follow-Up Would Look Like

For reference, and for anyone extending this work:

1. **Placebo test** — re-run DiD with treatment date = 2024-01-05, expect β₃ ≈ 0
2. **Exclude Queens from control** — re-estimate with only Brooklyn and Bronx as controls; compare β₃
3. **Event study** — replace the single post-period dummy with month-by-month interaction terms to test for pre-trends and dynamic effects
4. **Synthetic control** — construct a weighted combination of control zones that best matches Manhattan's pre-period trend, then measure the post-period gap
5. **Mode substitution** — link to MTA subway ridership data to test whether the demand drop corresponds to a subway ridership increase in the same zones

---

## How to Reproduce

```bash
# Trigger the DAG manually for a given run date
airflow dags trigger congestion_pricing_analysis --conf '{"run_date": "2026-04-24"}'

# Or run the script directly
python ml/models/causal_inference/congestion_pricing_did.py --run-date 2026-04-24
```

Results are written to `NYC_TLC_DB.ML.FCT_CONGESTION_PRICING_IMPACT`.
Views `V_CONGESTION_BOROUGH_SUMMARY` and `V_CONGESTION_DID_BETA_SERIES` are defined
in `infra/scripts/congestion_pricing_views.sql`.

---

## Update Log

| Run date | β₃ trips | β₃ revenue | R² trips | Notes |
|---|---|---|---|---|
| 2026-04-24 | −75.30 | −$1,172 | 0.9272 | First run. ~15 months of post-period data. |

*This table will be updated as monthly re-runs accumulate.*
