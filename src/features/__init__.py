"""Centralized feature store for Lakay Intelligence.

All ML feature computation and serving flows through this package via Feast.
Feature definitions live in ``definitions/``, the Feast repository config lives
in ``feast_repo/``, and the client wrapper is in ``store.py``.
"""
