"""Feast feature definitions for fraud detection features."""

from datetime import timedelta

FRAUD_ENTITY_NAME = "user"
FRAUD_ENTITY_JOIN_KEY = "user_id"

FRAUD_FEATURE_SERVICE_NAME = "fraud_features_v1"

FRAUD_FEATURES: list[dict[str, str]] = [
    {"name": "login_count_10m", "dtype": "Int64", "description": "Login attempts in the last 10 minutes."},
    {"name": "login_count_1h", "dtype": "Int64", "description": "Login attempts in the last hour."},
    {"name": "tx_count_1h", "dtype": "Int64", "description": "Transactions in the last hour."},
    {"name": "tx_count_24h", "dtype": "Int64", "description": "Transactions in the last 24 hours."},
    {"name": "circle_joins_24h", "dtype": "Int64", "description": "Circles joined in the last 24 hours."},
    {"name": "tx_amount_last", "dtype": "Float64", "description": "Most recent transaction amount."},
    {"name": "tx_amount_mean_30d", "dtype": "Float64", "description": "Mean transaction amount over 30 days."},
    {"name": "tx_amount_std_30d", "dtype": "Float64", "description": "Transaction amount stddev over 30 days."},
    {"name": "tx_amount_zscore", "dtype": "Float64", "description": "Current transaction z-score versus 30 day history."},
    {"name": "tx_cumulative_24h", "dtype": "Float64", "description": "Cumulative transaction amount in last 24 hours."},
    {"name": "tx_cumulative_7d", "dtype": "Float64", "description": "Cumulative transaction amount in last 7 days."},
    {"name": "ctr_proximity_score", "dtype": "Float64", "description": "Proximity to $10,000 daily CTR threshold."},
    {"name": "last_known_country", "dtype": "String", "description": "Country of most recent authenticated event."},
    {"name": "last_known_city", "dtype": "String", "description": "City of most recent authenticated event."},
    {"name": "distinct_countries_7d", "dtype": "Int64", "description": "Distinct countries in 7 days."},
    {"name": "max_travel_speed_24h", "dtype": "Float64", "description": "Max implied travel speed over 24h."},
    {"name": "duplicate_tx_count_1h", "dtype": "Int64", "description": "Near-identical transactions in last hour."},
    {"name": "same_recipient_tx_sum_24h", "dtype": "Float64", "description": "Amount sent to same recipient in 24h."},
    {"name": "round_amount_ratio_30d", "dtype": "Float64", "description": "Round amount transaction ratio over 30 days."},
    {"name": "tx_time_regularity_score", "dtype": "Float64", "description": "Clock-like regularity score for tx timing."},
]

FRAUD_TTL_BY_FEATURE: dict[str, timedelta] = {
    "login_count_10m": timedelta(minutes=10),
    "login_count_1h": timedelta(hours=1),
    "tx_count_1h": timedelta(hours=1),
    "tx_count_24h": timedelta(hours=24),
    "circle_joins_24h": timedelta(hours=24),
    "tx_amount_last": timedelta(days=1),
    "tx_amount_mean_30d": timedelta(days=30),
    "tx_amount_std_30d": timedelta(days=30),
    "tx_amount_zscore": timedelta(days=1),
    "tx_cumulative_24h": timedelta(hours=24),
    "tx_cumulative_7d": timedelta(days=7),
    "ctr_proximity_score": timedelta(days=1),
    "last_known_country": timedelta(days=7),
    "last_known_city": timedelta(days=7),
    "distinct_countries_7d": timedelta(days=7),
    "max_travel_speed_24h": timedelta(hours=24),
    "duplicate_tx_count_1h": timedelta(hours=1),
    "same_recipient_tx_sum_24h": timedelta(hours=24),
    "round_amount_ratio_30d": timedelta(days=30),
    "tx_time_regularity_score": timedelta(days=30),
}

FRAUD_FEATURE_REFS = [f"fraud_user_features:{feature['name']}" for feature in FRAUD_FEATURES]
