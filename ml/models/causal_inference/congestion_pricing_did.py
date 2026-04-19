"""Congestion pricing DiD causal inference (Phase 8).

Fits difference-in-differences regression:
    Y = α + β₁·post + β₂·treated + β₃·(post × treated) + ε

Treatment : Manhattan CBD Yellow Zone (pickup_borough = 'Manhattan', service_zone = 'Yellow Zone')
Control   : Brooklyn, Queens, Bronx
Pre period: 2024-01-01 to 2025-01-04
Post period: 2025-01-05 onward (CBD congestion pricing effective date)

Writes results to NYC_TLC_DB.ML.fct_congestion_pricing_impact.
Contract  : .claude/ML_FEATURE_CONTRACTS.md §Model 3

Usage: python congestion_pricing_did.py --run-date YYYY-MM-DD
"""
