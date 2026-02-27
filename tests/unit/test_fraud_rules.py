"""Unit tests for fraud detection rules (backward-compat integration tests).

These tests verify the rules package exports and haversine utility.
Individual rule tests are in test_velocity_rules.py, test_amount_rules.py,
test_geo_rules.py, and test_pattern_rules.py.
"""

from src.domains.fraud.rules import ALL_RULES, FraudRule, haversine


class TestHaversine:
    def test_same_point(self):
        assert haversine(0, 0, 0, 0) == 0

    def test_known_distance(self):
        # NYC to London ~5570 km
        d = haversine(40.7128, -74.0060, 51.5074, -0.1278)
        assert 5500 < d < 5650


class TestAllRules:
    def test_all_rules_is_list(self):
        assert isinstance(ALL_RULES, list)

    def test_all_rules_has_expected_count(self):
        # 6 velocity + 4 amount + 4 geo + 4 patterns = 18
        assert len(ALL_RULES) == 18

    def test_all_rules_are_fraud_rule_instances(self):
        for rule in ALL_RULES:
            assert isinstance(rule, FraudRule)

    def test_all_rules_have_required_attrs(self):
        for rule in ALL_RULES:
            assert hasattr(rule, "rule_id")
            assert hasattr(rule, "category")
            assert hasattr(rule, "default_weight")
            assert rule.category in ("velocity", "amount", "geo", "patterns")
            assert 0.0 < rule.default_weight <= 1.0

    def test_rule_ids_are_unique(self):
        ids = [r.rule_id for r in ALL_RULES]
        assert len(ids) == len(set(ids))
