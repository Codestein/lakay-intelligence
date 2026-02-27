"""Unit tests for the fraud alert pipeline."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domains.fraud.alerts import check_dedup, create_alert, publish_alert
from src.domains.fraud.config import FraudConfig
from src.domains.fraud.models import (
    FraudScoreRequest,
    RiskTier,
    RuleResult,
    ScoringContext,
)

CONFIG = FraudConfig()
NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)


def _make_request(**kwargs) -> FraudScoreRequest:
    defaults = {
        "transaction_id": "txn-1",
        "user_id": "user-1",
        "amount": "5000.00",
        "initiated_at": NOW,
    }
    defaults.update(kwargs)
    return FraudScoreRequest(**defaults)


def _make_scoring_context(score: float, tier: RiskTier) -> ScoringContext:
    triggered = []
    if score > 0:
        triggered.append(
            RuleResult(
                rule_name="large_transaction",
                triggered=True,
                score=score,
                details="test",
                category="amount",
            )
        )
    return ScoringContext(
        composite_score=score,
        risk_tier=tier,
        triggered_rules=triggered,
        recommendation={"low": "allow", "medium": "monitor", "high": "hold", "critical": "block"}[
            tier.value
        ],
        scoring_metadata={"model_version": "rules-v2"},
    )


def _mock_session(existing_alerts: int = 0):
    session = AsyncMock()
    session.add = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = existing_alerts
    session.execute.return_value = mock_result
    return session


class TestCheckDedup:
    @pytest.mark.asyncio
    async def test_no_existing_alerts(self):
        session = _mock_session(existing_alerts=0)
        is_dup = await check_dedup("user-1", ["rule-a"], session)
        assert not is_dup

    @pytest.mark.asyncio
    async def test_existing_alerts(self):
        session = _mock_session(existing_alerts=2)
        is_dup = await check_dedup("user-1", ["rule-a"], session)
        assert is_dup

    @pytest.mark.asyncio
    async def test_custom_suppression_window(self):
        session = _mock_session(existing_alerts=1)
        is_dup = await check_dedup("user-1", ["rule-a"], session, suppression_window_seconds=60)
        assert is_dup


class TestCreateAlert:
    @pytest.mark.asyncio
    async def test_low_risk_no_alert(self):
        ctx = _make_scoring_context(0.2, RiskTier.LOW)
        session = _mock_session()
        alert = await create_alert(ctx, _make_request(), session, CONFIG)
        assert alert is None

    @pytest.mark.asyncio
    async def test_medium_risk_no_alert(self):
        ctx = _make_scoring_context(0.4, RiskTier.MEDIUM)
        session = _mock_session()
        alert = await create_alert(ctx, _make_request(), session, CONFIG)
        assert alert is None

    @pytest.mark.asyncio
    async def test_high_risk_creates_alert(self):
        ctx = _make_scoring_context(0.7, RiskTier.HIGH)
        session = _mock_session(existing_alerts=0)
        alert = await create_alert(ctx, _make_request(), session, CONFIG)
        assert alert is not None
        assert alert.severity == "high"
        assert alert.user_id == "user-1"
        assert alert.status == "new"
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_critical_risk_creates_alert(self):
        ctx = _make_scoring_context(0.9, RiskTier.CRITICAL)
        session = _mock_session(existing_alerts=0)
        alert = await create_alert(ctx, _make_request(), session, CONFIG)
        assert alert is not None
        assert alert.severity == "critical"

    @pytest.mark.asyncio
    async def test_dedup_suppresses_alert(self):
        ctx = _make_scoring_context(0.8, RiskTier.HIGH)
        session = _mock_session(existing_alerts=1)  # Existing alert
        alert = await create_alert(ctx, _make_request(), session, CONFIG)
        assert alert is None

    @pytest.mark.asyncio
    async def test_alert_details_populated(self):
        ctx = _make_scoring_context(0.75, RiskTier.HIGH)
        session = _mock_session(existing_alerts=0)
        alert = await create_alert(ctx, _make_request(), session, CONFIG)
        assert alert is not None
        assert alert.details["transaction_id"] == "txn-1"
        assert alert.details["composite_score"] == 0.75
        assert alert.details["risk_tier"] == "high"
        assert "triggered_rules" in alert.details


class TestPublishAlert:
    @pytest.mark.asyncio
    async def test_publish_to_kafka(self):
        producer = AsyncMock()
        alert = MagicMock()
        alert.alert_id = "alert-1"
        alert.user_id = "user-1"
        alert.alert_type = "fraud_score"
        alert.severity = "high"
        alert.details = {"test": True}
        alert.status = "new"
        alert.created_at = NOW

        await publish_alert(alert, producer)

        producer.send_and_wait.assert_awaited_once()
        call_args = producer.send_and_wait.call_args
        # topic is the first positional arg
        assert call_args.args[0] == "lakay.fraud.alerts"

    @pytest.mark.asyncio
    async def test_no_producer(self):
        alert = MagicMock()
        alert.alert_id = "alert-1"
        # Should not raise
        await publish_alert(alert, None)

    @pytest.mark.asyncio
    async def test_publish_failure_logged(self):
        producer = AsyncMock()
        producer.send_and_wait.side_effect = Exception("Kafka down")
        alert = MagicMock()
        alert.alert_id = "alert-1"
        alert.user_id = "user-1"
        alert.alert_type = "fraud_score"
        alert.severity = "high"
        alert.details = {}
        alert.status = "new"
        alert.created_at = NOW

        # Should not raise, just log
        await publish_alert(alert, producer)
