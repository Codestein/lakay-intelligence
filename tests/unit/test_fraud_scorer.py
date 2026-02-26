"""Unit tests for the fraud scorer pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domains.fraud.models import FraudScoreRequest, TransactionFeatures
from src.domains.fraud.scorer import ALERT_THRESHOLD, BLOCK_THRESHOLD, FraudScorer


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def scorer():
    return FraudScorer()


def _make_request(**kwargs) -> FraudScoreRequest:
    defaults = {
        "transaction_id": "txn-test-1",
        "user_id": "user-test-1",
        "amount": "100.00",
    }
    defaults.update(kwargs)
    return FraudScoreRequest(**defaults)


class TestFraudScorer:
    @pytest.mark.asyncio
    async def test_low_risk_no_alert(self, scorer, mock_session):
        request = _make_request(amount="50.00")
        with patch.object(
            scorer._feature_computer,
            "compute",
            return_value=TransactionFeatures(),
        ):
            result = await scorer.score_transaction(request, mock_session)

        assert result.final_score == 0
        # One call for FraudScore row, no alert
        assert mock_session.add.call_count == 1
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_high_score_creates_alert(self, scorer, mock_session):
        request = _make_request(amount="9700.00")
        features = TransactionFeatures(
            velocity_count_1h=10,
            is_new_device=True,
            is_new_country=True,
        )
        with patch.object(scorer._feature_computer, "compute", return_value=features):
            result = await scorer.score_transaction(request, mock_session)

        assert result.final_score >= ALERT_THRESHOLD
        # FraudScore + Alert = 2 add calls
        assert mock_session.add.call_count == 2

    @pytest.mark.asyncio
    async def test_critical_severity_above_block_threshold(self, scorer, mock_session):
        request = _make_request(amount="9900.00")
        features = TransactionFeatures(
            velocity_count_1h=15,
            velocity_count_24h=25,
            velocity_amount_24h=40000,
            is_new_device=True,
            is_new_country=True,
        )
        with patch.object(scorer._feature_computer, "compute", return_value=features):
            result = await scorer.score_transaction(request, mock_session)

        # Check alert severity
        if result.final_score >= BLOCK_THRESHOLD:
            alert_call = mock_session.add.call_args_list[1]
            alert_obj = alert_call[0][0]
            assert alert_obj.severity == "critical"

    @pytest.mark.asyncio
    async def test_scoring_result_has_features(self, scorer, mock_session):
        request = _make_request()
        features = TransactionFeatures(velocity_count_1h=3)
        with patch.object(scorer._feature_computer, "compute", return_value=features):
            result = await scorer.score_transaction(request, mock_session)

        assert result.features_used is not None
        assert result.features_used.velocity_count_1h == 3
