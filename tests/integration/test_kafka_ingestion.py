"""Integration tests for Kafka event ingestion."""

import pytest

pytestmark = pytest.mark.integration


class TestKafkaIngestion:
    def test_circle_consumer_has_handlers(self):
        from src.consumers.circle_consumer import CircleConsumer

        consumer = CircleConsumer(bootstrap_servers="localhost:9092", group_id="test-group")
        assert "circle-created" in consumer.handlers
        assert "circle-member-joined" in consumer.handlers
        assert "circle-contribution-received" in consumer.handlers

    def test_transaction_consumer_has_handlers(self):
        from src.consumers.transaction_consumer import TransactionConsumer

        consumer = TransactionConsumer(bootstrap_servers="localhost:9092", group_id="test-group")
        assert "transaction-initiated" in consumer.handlers
        assert "transaction-completed" in consumer.handlers

    def test_session_consumer_has_handlers(self):
        from src.consumers.session_consumer import SessionConsumer

        consumer = SessionConsumer(bootstrap_servers="localhost:9092", group_id="test-group")
        assert "login-attempt" in consumer.handlers
        assert "session-started" in consumer.handlers
        assert "user-action-performed" in consumer.handlers

    def test_remittance_consumer_has_handlers(self):
        from src.consumers.remittance_consumer import RemittanceConsumer

        consumer = RemittanceConsumer(bootstrap_servers="localhost:9092", group_id="test-group")
        assert "remittance-initiated" in consumer.handlers
        assert "exchange-rate-updated" in consumer.handlers
