"""Tests for the A/B experimentation framework."""

import hashlib

import pytest

from src.pipeline.experiment_models import (
    AssignmentStrategy,
    CreateExperimentRequest,
    ExperimentStatus,
    ExperimentVariant,
)
from src.pipeline.experimentation import _hash_assignment


class TestDeterministicAssignment:
    def test_consistent_assignment(self):
        """Same user + experiment → same variant every time."""
        v1 = _hash_assignment("user-123", "exp-001", 2)
        v2 = _hash_assignment("user-123", "exp-001", 2)
        assert v1 == v2

    def test_different_users_can_differ(self):
        """Different users may get different variants."""
        results = set()
        for i in range(100):
            v = _hash_assignment(f"user-{i}", "exp-001", 2)
            results.add(v)
        # With 100 users and 2 variants, we should see both
        assert len(results) == 2

    def test_different_experiments_differ(self):
        """Same user in different experiments can get different variants."""
        results = set()
        for i in range(20):
            v = _hash_assignment("user-1", f"exp-{i}", 2)
            results.add(v)
        # Should see both variants across different experiments
        assert len(results) == 2

    def test_uniform_distribution(self):
        """Assignment should be roughly uniform across variants."""
        counts = {0: 0, 1: 0}
        num_users = 10000
        for i in range(num_users):
            v = _hash_assignment(f"user-{i}", "exp-uniform-test", 2)
            counts[v] += 1
        # Each variant should get roughly 50% (within 5% tolerance)
        for count in counts.values():
            ratio = count / num_users
            assert 0.45 <= ratio <= 0.55, f"Non-uniform distribution: {counts}"

    def test_100k_consistency(self):
        """Assignment is deterministic across 100K simulated users."""
        assignments = {}
        for i in range(100_000):
            uid = f"user-{i}"
            assignments[uid] = _hash_assignment(uid, "exp-consistency", 3)

        # Verify consistency
        for i in range(100_000):
            uid = f"user-{i}"
            assert assignments[uid] == _hash_assignment(uid, "exp-consistency", 3)

    def test_three_variants(self):
        """Works correctly with 3 variants."""
        counts = {0: 0, 1: 0, 2: 0}
        for i in range(9000):
            v = _hash_assignment(f"user-{i}", "exp-3way", 3)
            counts[v] += 1
        # Each variant should get roughly 33%
        for count in counts.values():
            ratio = count / 9000
            assert 0.28 <= ratio <= 0.38, f"Non-uniform 3-way: {counts}"


class TestExperimentModels:
    def test_create_request(self):
        req = CreateExperimentRequest(
            name="Test Experiment",
            description="Testing new fraud model",
            hypothesis="New model reduces false positives",
            variants=[
                ExperimentVariant(variant_id="control", name="control", config={"model": "v1"}),
                ExperimentVariant(variant_id="treatment", name="treatment", config={"model": "v2"}),
            ],
            primary_metric="false_positive_rate",
            guardrail_metrics=["scoring_latency_p95_ms"],
        )
        assert req.name == "Test Experiment"
        assert len(req.variants) == 2
        assert req.assignment_strategy == AssignmentStrategy.USER_HASH

    def test_variant_config(self):
        variant = ExperimentVariant(
            variant_id="treatment_a",
            name="treatment_a",
            config={"threshold": 0.7, "model_version": "fraud-detector-v0.3"},
        )
        assert variant.config["threshold"] == 0.7

    def test_status_enum(self):
        assert ExperimentStatus.DRAFT == "draft"
        assert ExperimentStatus.RUNNING == "running"
        assert ExperimentStatus.COMPLETED == "completed"
