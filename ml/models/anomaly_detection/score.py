"""Anomaly detection — daily scoring script (Phase 9).

Computes z-scores against the rolling 30-day baseline and writes
flagged rows to NYC_TLC_DB.ML.fct_anomalies.

Usage: python score.py --run-date YYYY-MM-DD
"""
