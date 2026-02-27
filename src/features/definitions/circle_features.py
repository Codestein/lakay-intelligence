"""Feast feature definitions for circle health scoring."""

CIRCLE_FEATURES: list[dict[str, str]] = [
    {"name": "on_time_payment_rate", "dtype": "Float64", "description": "Pct contributions received on/before due date."},
    {"name": "avg_days_late", "dtype": "Float64", "description": "Average days late for late contributions."},
    {"name": "missed_contribution_count", "dtype": "Int64", "description": "Total missed contributions to date."},
    {"name": "consecutive_on_time_streak", "dtype": "Int64", "description": "Current on-time streak across members."},
    {"name": "member_count_current", "dtype": "Int64", "description": "Current active member count."},
    {"name": "member_drop_count", "dtype": "Int64", "description": "Members dropped out."},
    {"name": "member_drop_rate", "dtype": "Float64", "description": "Drop count / original member count."},
    {"name": "avg_member_tenure_days", "dtype": "Float64", "description": "Average member tenure days."},
    {"name": "total_collected_amount", "dtype": "Float64", "description": "Total contributions collected to date."},
    {"name": "expected_collected_amount", "dtype": "Float64", "description": "Expected total collection by schedule."},
    {"name": "collection_ratio", "dtype": "Float64", "description": "total_collected / expected_collected."},
    {"name": "payout_completion_count", "dtype": "Int64", "description": "Successful payouts completed."},
    {"name": "payout_completion_rate", "dtype": "Float64", "description": "Completed payouts / expected payouts."},
    {"name": "largest_single_missed_amount", "dtype": "Float64", "description": "Largest missed contribution amount."},
    {"name": "late_payment_trend", "dtype": "Float64", "description": "Slope of rolling late-payment rate."},
    {"name": "coordinated_behavior_score", "dtype": "Float64", "description": "Correlation-like suspicious coordination score."},
]

CIRCLE_FEATURE_REFS = [f"circle_health_features:{feature['name']}" for feature in CIRCLE_FEATURES]
