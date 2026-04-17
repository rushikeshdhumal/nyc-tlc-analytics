# ADR-002: fct_revenue_daily Reads from Gold Hourly, Not Silver

| Field       | Value                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Date**    | 2026-04-17                   |
| **Author**  | Rushikesh Dhumal             |

---

## Context

`fct_revenue_daily` is a pre-aggregated Gold model at `pickup_date ×
pu_location_id` grain, built to reduce Snowflake compute for Superset
dashboard queries. When designing its source, two options were considered:
read from Silver (`stg_yellow_tripdata`) or read from the existing Gold hourly
model (`fct_revenue_per_zone_hourly`).

The choice is non-obvious because reading from Silver is the more conventional
dbt pattern — Gold models typically read from Silver, not from each other.

---

## Decision

`fct_revenue_daily` reads from **`fct_revenue_per_zone_hourly`** (Gold → Gold),
not from Silver directly.

---

## Options Considered

| Option | Pros | Cons |
|--------|------|------|
| **Gold → Gold (chosen)** | No duplicated transformation logic; business rules (payment filter, NULL guards, COALESCE, ROUND) defined once in hourly; daily inherits correct values via simple SUM/weighted average | Non-standard dbt layering; daily model depends on hourly being built first |
| **Silver → Gold (conventional)** | Standard dbt pattern; daily model is independent of hourly | All transformation logic (payment_type filter, COALESCE, ROUND, vendor decode) must be duplicated; two places to update when business rules change |

---

## Reasoning

The hourly model encodes several non-trivial business rules:

- `payment_type NOT IN (3, 4, 6)` — excludes no-charge, dispute, and void trips from revenue
- `COALESCE(pickup_borough, 'Unknown')` — guards against unmatched zone IDs
- `tip_amount` NULLed for non-credit-card trips to prevent misleading averages
- `ROUND` applied to all float metrics

Duplicating these rules in a Silver-sourced daily model creates two maintenance
surfaces. Any future change to the revenue definition (e.g. adding a new
excluded payment type) would require updating both models. Reading from the
hourly model means the daily model inherits correct, already-validated values
and only needs to perform straightforward aggregation.

The daily model's aggregations are all mathematically sound from the hourly
base: additive metrics (revenue, distance, trip count) sum directly; rate
metrics (avg duration, credit card %, tip %) use trip-count-weighted averages
that recover the correct daily figure.

---

## Consequences

**Positive**
- Business rules are defined once, in the hourly model, and flow down to daily automatically.
- `fct_revenue_daily` is a thin aggregation layer with no duplicated logic — easier to maintain and audit.
- dbt enforces the build order: daily runs after hourly due to the `ref()` dependency.

**Trade-offs**
- The daily model has a hard dependency on the hourly model. If hourly fails, daily is skipped. This is acceptable — a broken hourly model means the daily figures would be wrong anyway.
- Gold-on-Gold layering is unconventional and may surprise a developer unfamiliar with this codebase. This ADR serves as the explanation.

---

## Files Changed

| File | Change |
|------|--------|
| `transform/models/gold/fct_revenue_daily.sql` | New — daily Gold model reading from `fct_revenue_per_zone_hourly` |
| `transform/models/gold/fct_revenue_daily.yml` | New — column descriptions and not_null / unique tests |
