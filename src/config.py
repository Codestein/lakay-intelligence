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

    # Data lake (MinIO/S3)
    datalake_endpoint: str = "http://localhost:9000"
    datalake_access_key: str = "minioadmin"
    datalake_secret_key: str = "minioadmin"
    datalake_bucket: str = "lakay-data-lake"

    # PII tokenization
    pii_token_secret: str = "lakay-pii-token-secret-dev-only"
    pii_encryption_key: str = "lakay-encryption-key-dev-only"

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}


settings = Settings()
