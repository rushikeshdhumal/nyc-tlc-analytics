"""Anomaly detection — baseline training script (Phase 9).

Computes rolling 30-day mean and std per zone from fct_revenue_daily.
Logs baseline statistics to MLflow under 'anomaly_detection_daily'.

Usage: python train.py --run-date YYYY-MM-DD
"""
