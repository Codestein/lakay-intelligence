"""Tests for experiment metrics and statistical analysis."""

import math

import pytest

from src.pipeline.metrics import _approximate_p_value, _mean, _variance


class TestHelperFunctions:
    def test_mean_basic(self):
        assert _mean([1.0, 2.0, 3.0]) == 2.0

    def test_mean_single(self):
        assert _mean([5.0]) == 5.0

    def test_mean_empty(self):
        assert _mean([]) == 0.0

    def test_variance_basic(self):
        # Population: [1, 2, 3], sample variance = 1.0
        v = _variance([1.0, 2.0, 3.0])
        assert abs(v - 1.0) < 0.001

    def test_variance_constant(self):
        assert _variance([5.0, 5.0, 5.0]) == 0.0

    def test_variance_single(self):
        assert _variance([1.0]) == 0.0

    def test_variance_empty(self):
        assert _variance([]) == 0.0


class TestPValue:
    def test_zero_t_stat(self):
        p = _approximate_p_value(0.0, 100)
        assert p == 1.0

    def test_large_t_stat(self):
        p = _approximate_p_value(5.0, 100)
        assert p < 0.001

    def test_moderate_t_stat(self):
        p = _approximate_p_value(2.0, 100)
        assert 0.01 < p < 0.1

    def test_small_t_stat(self):
        p = _approximate_p_value(0.5, 100)
        assert p > 0.5

    def test_p_value_bounded(self):
        """P-value should always be in [0, 1]."""
        for t in [0, 0.1, 1, 2, 3, 5, 10, 20]:
            p = _approximate_p_value(float(t), 100.0)
            assert 0.0 <= p <= 1.0
