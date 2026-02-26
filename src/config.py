"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "lakay-intelligence"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "postgresql+asyncpg://lakay:lakay_dev@localhost:5432/lakay"

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_consumer_group: str = "lakay-intelligence"
    kafka_auto_offset_reset: str = "earliest"

    redis_url: str = "redis://localhost:6379/0"

    contracts_path: str = "../trebanx-contracts/schemas"

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}


settings = Settings()
