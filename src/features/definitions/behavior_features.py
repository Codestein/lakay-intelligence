"""Feast feature definitions for user behavior and ATO analytics."""

BEHAVIOR_FEATURES: list[dict[str, str]] = [
    {"name": "avg_session_duration_30d", "dtype": "Float64", "description": "Mean session duration in seconds over 30d."},
    {"name": "session_count_7d", "dtype": "Int64", "description": "Number of sessions in last 7d."},
    {"name": "avg_actions_per_session_30d", "dtype": "Float64", "description": "Mean actions/session over 30d."},
    {"name": "distinct_devices_30d", "dtype": "Int64", "description": "Distinct devices in last 30d."},
    {"name": "distinct_ips_7d", "dtype": "Int64", "description": "Distinct IPs in last 7d."},
    {"name": "new_device_flag", "dtype": "Bool", "description": "Current session uses unseen device."},
    {"name": "days_since_last_login", "dtype": "Float64", "description": "Days since most recent login."},
    {"name": "login_streak_days", "dtype": "Int64", "description": "Consecutive login days streak."},
    {"name": "feature_usage_breadth", "dtype": "Int64", "description": "Distinct platform features used in 30d."},
    {"name": "typical_login_hour_mean", "dtype": "Float64", "description": "Mean login hour in 30d."},
    {"name": "typical_login_hour_std", "dtype": "Float64", "description": "Stddev login hour in 30d."},
    {"name": "current_session_hour_deviation", "dtype": "Float64", "description": "Z-like deviation from typical login hour."},
]

BEHAVIOR_FEATURE_REFS = [f"behavior_user_features:{feature['name']}" for feature in BEHAVIOR_FEATURES]
