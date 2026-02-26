"""Tests for application configuration."""

from src.config import Settings


class TestSettings:
    def test_default_settings(self):
        settings = Settings()
        assert settings.app_name == "lakay-intelligence"
        assert settings.app_version == "0.1.0"
        assert settings.port == 8000

    def test_settings_from_env(self, monkeypatch):
        monkeypatch.setenv("APP_NAME", "test-app")
        monkeypatch.setenv("PORT", "9000")
        monkeypatch.setenv("DEBUG", "true")
        settings = Settings()
        assert settings.app_name == "test-app"
        assert settings.port == 9000
        assert settings.debug is True

    def test_database_url_default(self):
        settings = Settings()
        assert "postgresql+asyncpg" in settings.database_url

    def test_kafka_settings(self):
        settings = Settings()
        assert settings.kafka_consumer_group == "lakay-intelligence"
