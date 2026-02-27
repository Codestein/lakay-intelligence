# Configuration Reference

Phase 10 -- Task 10.5: Complete configuration parameter reference.

Every configurable parameter across all Lakay Intelligence modules is documented
here. Parameters are grouped by module with their types, defaults, environment
variable names, and descriptions.

---

## Core Settings

**Source:** `src/config.py` (Pydantic `BaseSettings`, loaded from env vars and `.env`)

| Parameter                  | Env Var                    | Type   | Default                                                     | Description                                |
|----------------------------|----------------------------|--------|-------------------------------------------------------------|--------------------------------------------|
| `app_name`                 | `APP_NAME`                 | `str`  | `"lakay-intelligence"`                                      | Application name for logging and metrics   |
| `app_version`              | `APP_VERSION`              | `str`  | `"0.1.0"`                                                   | Application version                        |
| `debug`                    | `DEBUG`                    | `bool` | `False`                                                     | Enable debug mode                          |
| `log_level`                | `LOG_LEVEL`                | `str`  | `"INFO"`                                                    | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `host`                     | `HOST`                     | `str`  | `"0.0.0.0"`                                                 | HTTP server bind address                   |
| `port`                     | `PORT`                     | `int`  | `8000`                                                      | HTTP server port                           |
| `database_url`             | `DATABASE_URL`             | `str`  | `"postgresql+asyncpg://lakay:lakay_dev@localhost:5432/lakay"` | PostgreSQL async connection string        |
| `kafka_bootstrap_servers`  | `KAFKA_BOOTSTRAP_SERVERS`  | `str`  | `"localhost:9092"`                                          | Kafka broker addresses                     |
| `kafka_consumer_group`     | `KAFKA_CONSUMER_GROUP`     | `str`  | `"lakay-intelligence"`                                      | Kafka consumer group ID                    |
| `kafka_auto_offset_reset`  | `KAFKA_AUTO_OFFSET_RESET`  | `str`  | `"earliest"`                                                | Kafka offset reset policy                  |
| `redis_url`                | `REDIS_URL`                | `str`  | `"redis://localhost:6379/0"`                                | Redis connection URL                       |
| `contracts_path`           | `CONTRACTS_PATH`           | `str`  | `"../trebanx-contracts/schemas"`                            | Path to Trebanx contract schema files      |
| `datalake_endpoint`        | `DATALAKE_ENDPOINT`        | `str`  | `"http://localhost:9000"`                                   | MinIO/S3 endpoint for data lake            |
| `datalake_access_key`      | `DATALAKE_ACCESS_KEY`      | `str`  | `"minioadmin"`                                              | MinIO/S3 access key                        |
| `datalake_secret_key`      | `DATALAKE_SECRET_KEY`      | `str`  | `"minioadmin"`                                              | MinIO/S3 secret key                        |
| `datalake_bucket`          | `DATALAKE_BUCKET`          | `str`  | `"lakay-data-lake"`                                         | Data lake bucket name                      |
| `pii_token_secret`         | `PII_TOKEN_SECRET`         | `str`  | `"lakay-pii-token-secret-dev-only"`                         | HMAC secret for PII tokenization           |
| `pii_encryption_key`       | `PII_ENCRYPTION_KEY`       | `str`  | `"lakay-encryption-key-dev-only"`                           | Encryption key for PII storage             |

**Important:** The `pii_token_secret`, `pii_encryption_key`, `datalake_access_key`,
and `datalake_secret_key` values MUST be overridden in production. The defaults are
development-only placeholders.

---

## Fraud Detection Config

**Source:** `src/domains/fraud/config.py` (`FraudConfig` dataclass, `FRAUD_` env prefix)

### Velocity Thresholds

| Parameter                        | Env Var                       | Type    | Default    | Description                                |
|----------------------------------|-------------------------------|---------|------------|--------------------------------------------|
| `login_count_window_minutes`     | --                            | `int`   | `10`       | Window for counting login attempts         |
| `login_count_max`                | `FRAUD_LOGIN_COUNT_MAX`       | `int`   | `5`        | Max login attempts before flagging         |
| `txn_count_1h_max`              | `FRAUD_TXN_COUNT_1H_MAX`     | `int`   | `10`       | Max transactions in 1 hour                 |
| `txn_count_24h_max`             | --                            | `int`   | `20`       | Max transactions in 24 hours               |
| `txn_amount_24h_max`            | `FRAUD_TXN_AMOUNT_24H_MAX`   | `float` | `10000.0`  | Max transaction amount in 24 hours         |
| `circle_join_window_hours`       | --                            | `int`   | `24`       | Window for counting circle joins           |
| `circle_join_max`                | --                            | `int`   | `3`        | Max circle joins in window                 |

### Amount Thresholds

| Parameter                   | Env Var                         | Type    | Default    | Description                                  |
|-----------------------------|----------------------------------|---------|------------|----------------------------------------------|
| `large_txn_min`             | `FRAUD_LARGE_TXN_MIN`           | `float` | `3000.0`   | Minimum amount to flag as large transaction  |
| `cumulative_24h_max`        | --                               | `float` | `8000.0`   | 24-hour cumulative amount threshold          |
| `cumulative_7d_max`         | --                               | `float` | `25000.0`  | 7-day cumulative amount threshold            |
| `cumulative_30d_max`        | --                               | `float` | `50000.0`  | 30-day cumulative amount threshold           |
| `baseline_zscore_threshold` | --                               | `float` | `2.5`      | Z-score threshold vs user baseline           |
| `ctr_single_threshold`      | `FRAUD_CTR_SINGLE_THRESHOLD`    | `float` | `8000.0`   | Single-transaction CTR approach threshold    |
| `ctr_daily_threshold`       | `FRAUD_CTR_DAILY_THRESHOLD`     | `float` | `9000.0`   | Daily aggregate CTR approach threshold       |

### Geographic Thresholds

| Parameter                    | Env Var | Type           | Default        | Description                                |
|------------------------------|---------|----------------|----------------|--------------------------------------------|
| `impossible_travel_speed_kmh` | --     | `float`        | `900.0`        | Speed threshold for impossible travel (km/h) |
| `home_countries`             | --      | `tuple[str]`   | `("US", "HT")` | Expected home countries for users          |

### Pattern Thresholds

| Parameter                        | Env Var | Type             | Default          | Description                                      |
|----------------------------------|---------|------------------|------------------|--------------------------------------------------|
| `duplicate_tolerance_pct`        | --      | `float`          | `0.05`           | Tolerance for duplicate detection (5%)           |
| `duplicate_window_minutes`       | --      | `int`            | `10`             | Window for duplicate transaction detection       |
| `structuring_3k_range`           | --      | `tuple[float]`   | `(2800, 2999)`   | Amount range for $3K structuring detection        |
| `structuring_10k_range`          | --      | `tuple[float]`   | `(9500, 9999)`   | Amount range for $10K structuring detection       |
| `structuring_window_hours`       | --      | `int`            | `24`             | Time window for structuring pattern detection    |
| `round_amount_pct_threshold`     | --      | `float`          | `0.60`           | Threshold for suspicious round-amount ratio      |
| `round_amount_lookback_days`     | --      | `int`            | `30`             | Lookback period for round-amount analysis        |
| `temporal_stddev_threshold_seconds` | --   | `float`          | `300.0`          | Std dev threshold for temporal pattern detection |
| `temporal_min_txns`              | --      | `int`            | `4`              | Minimum transactions for temporal analysis       |
| `temporal_lookback_days`         | --      | `int`            | `7`              | Lookback period for temporal analysis            |

### Scoring Weights (Category Caps)

| Parameter       | Env Var | Type    | Default | Description                               |
|-----------------|---------|---------|---------|-------------------------------------------|
| `velocity_cap`  | --      | `float` | `0.35`  | Maximum contribution from velocity signals |
| `amount_cap`    | --      | `float` | `0.30`  | Maximum contribution from amount signals   |
| `geo_cap`       | --      | `float` | `0.25`  | Maximum contribution from geo signals      |
| `patterns_cap`  | --      | `float` | `0.30`  | Maximum contribution from pattern signals  |

### Alert Settings

| Parameter                     | Env Var                     | Type    | Default                | Description                                    |
|-------------------------------|------------------------------|---------|------------------------|------------------------------------------------|
| `high_threshold`              | `FRAUD_HIGH_THRESHOLD`       | `float` | `0.6`                  | Score threshold for high-severity alert        |
| `critical_threshold`          | `FRAUD_CRITICAL_THRESHOLD`   | `float` | `0.8`                  | Score threshold for critical-severity alert    |
| `suppression_window_seconds`  | --                           | `int`   | `3600`                 | Alert deduplication window (1 hour)            |
| `kafka_topic`                 | `FRAUD_ALERT_KAFKA_TOPIC`    | `str`   | `"lakay.fraud.alerts"` | Kafka topic for fraud alerts                   |

---

## Circle Health Config

**Source:** `src/domains/circles/config.py` (`CircleHealthConfig` dataclass, `CIRCLE_` env prefix)

Dimension weights MUST sum to 1.0. Validated at construction time.

### Contribution Reliability (Dimension 1)

| Parameter                   | Env Var                        | Type    | Default | Description                                    |
|-----------------------------|--------------------------------|---------|---------|------------------------------------------------|
| `weight`                    | `CIRCLE_CONTRIBUTION_WEIGHT`   | `float` | `0.35`  | Dimension weight in composite score            |
| `on_time_rate_floor`        | --                             | `float` | `0.70`  | Below this on-time rate, score is 0            |
| `late_days_max_penalty`     | --                             | `int`   | `7`     | Days late at which full penalty applies         |
| `streak_bonus_threshold`    | --                             | `int`   | `3`     | Consecutive on-time payments for bonus         |
| `streak_bonus_max`          | --                             | `float` | `10.0`  | Maximum streak bonus points                    |
| `missed_penalty_first`      | --                             | `float` | `10.0`  | Score deduction for 1st missed contribution    |
| `missed_penalty_second`     | --                             | `float` | `20.0`  | Score deduction for 2nd missed contribution    |
| `missed_penalty_third_plus` | --                             | `float` | `30.0`  | Score deduction for 3rd+ missed contributions  |

### Membership Stability (Dimension 2)

| Parameter                   | Env Var                      | Type    | Default | Description                                    |
|-----------------------------|-------------------------------|---------|---------|------------------------------------------------|
| `weight`                    | `CIRCLE_MEMBERSHIP_WEIGHT`    | `float` | `0.25`  | Dimension weight in composite score            |
| `critical_drop_rate`        | --                            | `float` | `0.30`  | Drop rate at which score becomes 0             |
| `shrinkage_warning_ratio`   | --                            | `float` | `0.75`  | Current/original ratio triggering penalty      |
| `shrinkage_critical_ratio`  | --                            | `float` | `0.50`  | Current/original ratio at which score is 0     |
| `tenure_good_days`          | --                            | `int`   | `90`    | Days of tenure for full tenure bonus           |
| `tenure_bonus_max`          | --                            | `float` | `10.0`  | Maximum tenure bonus points                    |

### Financial Progress (Dimension 3)

| Parameter                 | Env Var                     | Type    | Default | Description                                  |
|---------------------------|------------------------------|---------|---------|----------------------------------------------|
| `weight`                  | `CIRCLE_FINANCIAL_WEIGHT`    | `float` | `0.25`  | Dimension weight in composite score          |
| `collection_ratio_floor`  | --                           | `float` | `0.60`  | Below this collection ratio, score is 0      |
| `payout_rate_floor`       | --                           | `float` | `0.50`  | Below this payout rate, score is 0           |
| `collection_sub_weight`   | --                           | `float` | `0.50`  | Sub-weight for collection ratio              |
| `payout_sub_weight`       | --                           | `float` | `0.30`  | Sub-weight for payout rate                   |
| `trajectory_sub_weight`   | --                           | `float` | `0.20`  | Sub-weight for trajectory trend              |

### Trust & Integrity (Dimension 4)

| Parameter                       | Env Var                 | Type    | Default | Description                                    |
|---------------------------------|--------------------------|---------|---------|------------------------------------------------|
| `weight`                        | `CIRCLE_TRUST_WEIGHT`    | `float` | `0.15`  | Dimension weight in composite score            |
| `coordinated_threshold`         | --                       | `float` | `0.70`  | Coordinated behavior score triggering penalty  |
| `missed_amount_ratio_threshold` | --                       | `float` | `2.0`   | Ratio of missed to typical amount flagging     |
| `disengagement_threshold`       | --                       | `float` | `0.30`  | Post-payout disengagement score threshold      |

### Trend Configuration

| Parameter                  | Env Var | Type    | Default | Description                                    |
|----------------------------|---------|---------|---------|------------------------------------------------|
| `improving_threshold`      | --      | `float` | `5.0`   | Score increase threshold for "improving" trend |
| `deteriorating_threshold`  | --      | `float` | `-5.0`  | Score decrease threshold for "deteriorating"   |
| `recent_weight`            | --      | `float` | `0.6`   | Weight for 1-cycle-ago comparison              |
| `historical_weight`        | --      | `float` | `0.4`   | Weight for 3-cycles-ago comparison             |

### General

| Parameter            | Env Var                     | Type   | Default                         | Description                        |
|----------------------|------------------------------|--------|---------------------------------|------------------------------------|
| `scoring_version`    | --                           | `str`  | `"circle-health-v1"`            | Scoring algorithm version tag      |
| `tier_change_topic`  | `CIRCLE_TIER_CHANGE_TOPIC`   | `str`  | `"lakay.circles.tier-changes"`  | Kafka topic for tier change events |

---

## Behavior Analytics Config

**Source:** `src/domains/behavior/config.py` (`BehaviorConfig` dataclass, `BEHAVIOR_` env prefix)

### Profile Configuration

| Parameter                     | Env Var                          | Type    | Default | Description                                       |
|-------------------------------|-----------------------------------|---------|---------|---------------------------------------------------|
| `min_sessions_active`         | `BEHAVIOR_MIN_SESSIONS_ACTIVE`    | `int`   | `10`    | Sessions before profile is "active"               |
| `min_days_active`             | --                                | `int`   | `7`     | Distinct days with sessions for "active"          |
| `ema_decay_rate`              | `BEHAVIOR_EMA_DECAY_RATE`         | `float` | `0.15`  | EMA alpha (0.1=slow, 0.3=fast)                   |
| `staleness_threshold_days`    | `BEHAVIOR_STALENESS_DAYS`         | `int`   | `30`    | Days of inactivity before profile is "stale"      |
| `stale_tolerance_multiplier`  | --                                | `float` | `1.5`   | Tolerance band widening for stale profiles        |
| `building_tolerance_multiplier` | --                              | `float` | `2.0`   | Tolerance band widening for building profiles     |
| `max_known_devices`           | --                                | `int`   | `20`    | Max tracked devices per user                      |
| `max_known_locations`         | --                                | `int`   | `30`    | Max tracked locations per user                    |

### Anomaly Dimension Weights

Weights MUST sum to 1.0. Validated at construction time.

| Parameter    | Env Var                      | Type    | Default | Description                          |
|--------------|-------------------------------|---------|---------|--------------------------------------|
| `temporal`   | `BEHAVIOR_TEMPORAL_WEIGHT`    | `float` | `0.15`  | Weight for time-of-day anomalies     |
| `device`     | `BEHAVIOR_DEVICE_WEIGHT`      | `float` | `0.25`  | Weight for device anomalies          |
| `geographic` | `BEHAVIOR_GEO_WEIGHT`         | `float` | `0.25`  | Weight for geographic anomalies      |
| `behavioral` | --                            | `float` | `0.25`  | Weight for session behavior anomalies |
| `engagement` | --                            | `float` | `0.10`  | Weight for engagement pattern anomalies |

### Anomaly Thresholds

| Parameter                      | Env Var | Type           | Default        | Description                                     |
|--------------------------------|---------|----------------|----------------|-------------------------------------------------|
| `normal_max`                   | --      | `float`        | `0.3`          | Max score for "normal" classification           |
| `suspicious_max`               | --      | `float`        | `0.6`          | Max score for "suspicious" classification       |
| `high_risk_max`                | --      | `float`        | `0.8`          | Max score for "high risk" (above = "critical")  |
| `temporal_zscore_high`         | --      | `float`        | `2.0`          | Z-score for high temporal anomaly               |
| `temporal_zscore_critical`     | --      | `float`        | `3.0`          | Z-score for critical temporal anomaly           |
| `new_device_score`             | --      | `float`        | `0.5`          | Anomaly score for unknown device                |
| `cross_platform_boost`         | --      | `float`        | `0.3`          | Score boost for cross-platform switch           |
| `impossible_travel_speed_kmh`  | --      | `float`        | `900.0`        | Impossible travel speed (km/h)                  |
| `corridor_countries`           | --      | `tuple[str]`   | `("US", "HT")` | Expected corridor countries                    |
| `corridor_reduction`           | --      | `float`        | `0.4`          | Score reduction for corridor travel             |
| `behavioral_zscore_high`       | --      | `float`        | `2.5`          | Z-score for high behavioral anomaly             |
| `bot_actions_per_second`       | --      | `float`        | `3.0`          | Actions/second threshold for bot detection      |
| `dormancy_days_warning`        | --      | `int`          | `14`           | Days since login for dormancy warning           |
| `dormancy_days_critical`       | --      | `int`          | `30`           | Days since login for critical dormancy          |

### Engagement Configuration

| Parameter                   | Env Var | Type    | Default | Description                                     |
|-----------------------------|---------|---------|---------|------------------------------------------------ |
| `new_max_sessions`          | --      | `int`   | `5`     | Max sessions for "new" lifecycle stage          |
| `new_max_days`              | --      | `int`   | `14`    | Max days for "new" lifecycle stage              |
| `onboarding_max_sessions`   | --      | `int`   | `15`    | Max sessions for "onboarding" stage             |
| `dormant_days`              | --      | `int`   | `14`    | Days inactive to classify as "dormant"          |
| `churned_days`              | --      | `int`   | `30`    | Days inactive to classify as "churned"          |
| `frequency_weight`          | --      | `float` | `0.30`  | Weight for login frequency in engagement score  |
| `recency_weight`            | --      | `float` | `0.25`  | Weight for login recency in engagement score    |
| `streak_weight`             | --      | `float` | `0.15`  | Weight for login streak in engagement score     |
| `breadth_weight`            | --      | `float` | `0.20`  | Weight for feature breadth in engagement score  |
| `consistency_weight`        | --      | `float` | `0.10`  | Weight for session consistency                  |
| `churn_score_drop_threshold` | --     | `float` | `20.0`  | Score-point drop triggering churn risk          |
| `churn_window_weeks`        | --      | `int`   | `3`     | Window for churn risk assessment                |

### ATO (Account Takeover) Configuration

| Parameter                      | Env Var                       | Type           | Default                             | Description                                    |
|--------------------------------|-------------------------------|----------------|-------------------------------------|------------------------------------------------|
| `anomaly_score_weight`         | --                            | `float`        | `0.30`                              | Weight of anomaly score in ATO risk            |
| `failed_logins_weight`         | --                            | `float`        | `0.15`                              | Weight of failed logins in ATO risk            |
| `new_device_location_weight`   | --                            | `float`        | `0.20`                              | Weight of new device/location in ATO risk      |
| `sensitive_actions_weight`     | --                            | `float`        | `0.20`                              | Weight of sensitive actions in ATO risk        |
| `impossible_travel_weight`     | --                            | `float`        | `0.15`                              | Weight of impossible travel in ATO risk        |
| `two_signal_multiplier`        | --                            | `float`        | `1.5`                               | Multiplier when 2 signals co-occur             |
| `three_signal_multiplier`      | --                            | `float`        | `2.0`                               | Multiplier when 3+ signals co-occur            |
| `low_max`                      | --                            | `float`        | `0.3`                               | Max score for "low" ATO risk                   |
| `moderate_max`                 | --                            | `float`        | `0.5`                               | Max score for "moderate" ATO risk              |
| `high_max`                     | --                            | `float`        | `0.8`                               | Max score for "high" ATO risk (above = critical) |
| `alert_dedup_window_seconds`   | `BEHAVIOR_ATO_DEDUP_WINDOW`   | `int`          | `86400`                             | Alert deduplication window (24 hours)          |
| `kafka_topic`                  | `BEHAVIOR_ATO_KAFKA_TOPIC`    | `str`          | `"lakay.behavior.ato-alerts"`       | Kafka topic for ATO alerts                     |
| `sensitive_actions`            | --                            | `tuple[str]`   | see below                           | Actions indicating potential ATO               |
| `failed_logins_10m_warning`    | --                            | `int`          | `3`                                 | Failed logins in 10 min for warning            |
| `failed_logins_1h_warning`     | --                            | `int`          | `5`                                 | Failed logins in 1 hour for warning            |

Sensitive actions list:
`change_email`, `change_phone`, `change_password`, `add_payment_method`,
`remove_payment_method`, `initiate_large_transaction`, `update_security_settings`,
`change_mfa_settings`

---

## Compliance Config

**Source:** `src/domains/compliance/config.py` (`ComplianceConfig` dataclass, `COMPLIANCE_` env prefix)

### CTR Threshold Monitoring (Rule M-1)

Regulatory basis: 31 CFR 1010.311

| Parameter               | Env Var                      | Type         | Default                                                        | Description                                     |
|-------------------------|-------------------------------|--------------|----------------------------------------------------------------|-------------------------------------------------|
| `enabled`               | `COMPLIANCE_CTR_ENABLED`      | `bool`       | `True`                                                         | Enable/disable CTR monitoring                   |
| `ctr_threshold`         | `COMPLIANCE_CTR_THRESHOLD`    | `float`      | `10000.0`                                                      | Federal CTR reporting threshold                 |
| `pre_threshold_warnings` | --                           | `list[float]` | `[8000.0, 9000.0]`                                            | Pre-threshold warning levels (80%, 90%)         |
| `cash_equivalent_types` | --                            | `list[str]`  | `[circle_contribution, circle_payout, remittance_send, remittance_receive]` | Transaction types treated as cash-equivalent |

### Round-Amount Patterns (Rule M-2)

Regulatory basis: FinCEN Advisory FIN-2014-A007, 31 USC 5324

| Parameter                      | Env Var | Type          | Default                    | Description                                  |
|--------------------------------|---------|---------------|----------------------------|----------------------------------------------|
| `enabled`                      | --      | `bool`        | `True`                     | Enable/disable round-amount monitoring       |
| `suspicious_amounts`           | --      | `list[float]` | `[9999, 4999, 2999]`      | Amounts near reporting thresholds            |
| `tolerance`                    | --      | `float`       | `10.0`                     | Tolerance band below threshold               |
| `round_amount_ratio_threshold` | --     | `float`       | `0.60`                     | Suspicious round-amount ratio threshold      |

### Rapid Movement Detection (Rule M-3)

Regulatory basis: 31 CFR 1022.320(a)(2)

| Parameter                 | Env Var                          | Type    | Default  | Description                                    |
|---------------------------|-----------------------------------|---------|----------|------------------------------------------------|
| `enabled`                 | --                                | `bool`  | `True`   | Enable/disable rapid movement monitoring       |
| `time_window_hours`       | `COMPLIANCE_RAPID_MOVEMENT_HOURS` | `int`   | `24`     | Window for detecting pass-through behavior     |
| `transfer_ratio_threshold` | `COMPLIANCE_RAPID_MOVEMENT_RATIO` | `float` | `0.80`  | Outbound/inbound ratio threshold               |
| `min_amount`              | --                                | `float` | `1000.0` | Minimum amount for rule activation             |

### Unusual Volume Detection (Rule M-4)

Regulatory basis: FinCEN Advisory FIN-2014-A007, 31 CFR 1022.210(d)

| Parameter                     | Env Var                          | Type    | Default | Description                                      |
|-------------------------------|-----------------------------------|---------|---------|--------------------------------------------------|
| `enabled`                     | --                                | `bool`  | `True`  | Enable/disable volume monitoring                 |
| `volume_multiplier_threshold` | `COMPLIANCE_VOLUME_MULTIPLIER`    | `float` | `3.0`   | Flag when volume exceeds Nx 30-day mean          |
| `min_baseline_transactions`   | --                                | `int`   | `5`     | Minimum history before rule activates            |
| `zscore_threshold`            | --                                | `float` | `3.0`   | Z-score threshold for amount anomaly             |

### Geographic Risk (Rule M-5)

Regulatory basis: 31 CFR 1022.210(d)(4), FATF Recommendation 19

| Parameter                  | Env Var | Type         | Default              | Description                                   |
|----------------------------|---------|--------------|----------------------|-----------------------------------------------|
| `enabled`                  | --      | `bool`       | `True`               | Enable/disable geographic risk monitoring     |
| `high_risk_countries`      | --      | `list[str]`  | `[IR, KP, MM, SY, YE, SO, LY, AF]` | FATF blacklist/greylist countries  |
| `expected_corridor_countries` | --   | `list[str]`  | `[US, HT]`          | Expected transaction origin countries         |
| `flag_unexpected_origin`   | --      | `bool`       | `True`               | Flag transactions from unexpected countries   |

### Circle Compliance (Rule M-6)

Regulatory basis: 31 CFR 1010.311 (aggregation), FinCEN IVTS guidance

| Parameter                            | Env Var | Type    | Default  | Description                                      |
|--------------------------------------|---------|---------|----------|--------------------------------------------------|
| `enabled`                            | --      | `bool`  | `True`   | Enable/disable circle compliance monitoring      |
| `circle_aggregate_warning_pct`       | --      | `float` | `0.80`   | Warning when aggregate reaches 80% of CTR        |
| `flag_circles_with_alerted_members`  | --      | `bool`  | `True`   | Flag circles containing alerted members          |
| `payout_monitoring_threshold`        | --      | `float` | `8000.0` | Payout amount triggering enhanced monitoring     |

### Structuring Detection

Regulatory basis: 31 USC 5324, 31 CFR 1010.311/1010.313

| Parameter                              | Env Var                                 | Type    | Default    | Description                                       |
|----------------------------------------|------------------------------------------|---------|------------|---------------------------------------------------|
| `enabled`                              | --                                       | `bool`  | `True`     | Enable/disable structuring detection              |
| `priority_override`                    | --                                       | `str`   | `"elevated"` | Default priority for structuring alerts          |
| `micro_min_transactions`               | --                                       | `int`   | `3`        | Same-recipient micro-structuring threshold        |
| `micro_min_total_transactions`         | --                                       | `int`   | `5`        | Any-recipient micro-structuring threshold         |
| `micro_cumulative_proximity_pct`       | --                                       | `float` | `0.80`     | Cumulative proximity to $10K (80%+)               |
| `slow_lookback_days`                   | `COMPLIANCE_STRUCTURING_LOOKBACK_DAYS`   | `int`   | `30`       | Lookback window for slow structuring              |
| `slow_min_transactions`                | --                                       | `int`   | `3`        | Min transactions for slow structuring             |
| `slow_amount_range_low`                | --                                       | `float` | `3000.0`   | Low end of suspicious slow-structuring range      |
| `slow_amount_range_high`               | --                                       | `float` | `9999.0`   | High end of suspicious slow-structuring range     |
| `slow_cumulative_threshold`            | --                                       | `float` | `10000.0`  | Cumulative threshold for slow structuring         |
| `fanout_min_recipients`                | --                                       | `int`   | `3`        | Min recipients for fan-out detection              |
| `fanout_rolling_window_hours`          | --                                       | `int`   | `48`       | Rolling window for fan-out detection              |
| `fanout_cumulative_threshold`          | --                                       | `float` | `10000.0`  | Cumulative threshold for fan-out                  |
| `funnel_min_senders`                   | --                                       | `int`   | `3`        | Min senders for funnel detection                  |
| `funnel_rolling_window_hours`          | --                                       | `int`   | `48`       | Rolling window for funnel detection               |
| `funnel_cumulative_threshold`          | --                                       | `float` | `10000.0`  | Cumulative threshold for funnel structuring       |
| `sar_confidence_threshold`             | `COMPLIANCE_SAR_CONFIDENCE`              | `float` | `0.70`     | Confidence above which SAR filing is recommended  |
| `enhanced_monitoring_confidence_threshold` | --                                  | `float` | `0.40`     | Confidence for enhanced monitoring recommendation |

### Customer Risk Scoring

Regulatory basis: 31 CFR 1022.210(d), FinCEN CDD Rule (31 CFR 1010.230)

| Parameter                | Env Var                    | Type    | Default | Description                                   |
|--------------------------|----------------------------|---------|---------|-----------------------------------------------|
| `enabled`                | --                         | `bool`  | `True`  | Enable/disable risk scoring                   |
| `low_max`                | `COMPLIANCE_RISK_LOW_MAX`  | `float` | `0.30`  | Max score for "low" risk level                |
| `medium_max`             | --                         | `float` | `0.60`  | Max score for "medium" risk level             |
| `high_max`               | `COMPLIANCE_RISK_HIGH_MAX` | `float` | `0.80`  | Max score for "high" risk (above = prohibited) |
| `transaction_weight`     | --                         | `float` | `0.30`  | Category weight: transaction patterns         |
| `geographic_weight`      | --                         | `float` | `0.25`  | Category weight: geographic risk              |
| `behavioral_weight`      | --                         | `float` | `0.25`  | Category weight: behavioral patterns          |
| `circle_weight`          | --                         | `float` | `0.20`  | Category weight: circle activity              |
| `low_review_days`        | --                         | `int`   | `365`   | Review frequency for low-risk customers       |
| `medium_review_days`     | --                         | `int`   | `90`    | Review frequency for medium-risk customers    |
| `high_review_days`       | --                         | `int`   | `30`    | Review frequency for high-risk customers      |
| `new_account_days`       | --                         | `int`   | `90`    | Account age for "new account" elevation       |
| `new_account_risk_boost` | --                         | `float` | `0.10`  | Risk score boost for new accounts             |

### Corridor Overrides (US-HT)

| Parameter                            | Env Var | Type    | Default  | Description                                     |
|--------------------------------------|---------|---------|----------|-------------------------------------------------|
| `corridor`                           | --      | `str`   | `"US-HT"` | Corridor identifier                            |
| `regular_remittance_max_amount`      | --      | `float` | `2000.0` | Max amount for regular remittance tolerance     |
| `regular_remittance_min_frequency_days` | --   | `int`   | `5`      | Min days between regular remittances            |
| `regular_remittance_max_frequency_days` | --   | `int`   | `35`     | Max days between regular remittances            |
| `regular_remittance_history_months`  | --      | `int`   | `6`      | Months of history for regular pattern recognition |

### Kafka Topics

| Parameter             | Env Var                          | Type  | Default                            | Description                          |
|-----------------------|-----------------------------------|-------|------------------------------------|--------------------------------------|
| `alerts_topic`        | `COMPLIANCE_ALERTS_TOPIC`         | `str` | `"lakay.compliance.alerts"`        | Kafka topic for compliance alerts    |
| `edd_triggers_topic`  | `COMPLIANCE_EDD_TRIGGERS_TOPIC`   | `str` | `"lakay.compliance.edd-triggers"`  | Kafka topic for EDD trigger events   |

---

## Serving Config

**Source:** `src/serving/config.py` (`ServingConfig` dataclass)

### Model Configuration

| Parameter                   | Env Var | Type    | Default                | Description                                |
|-----------------------------|---------|---------|------------------------|--------------------------------------------|
| `name`                      | --      | `str`   | `"fraud-detector-v0.1"` | Model name/identifier                     |
| `stage`                     | --      | `str`   | `"Production"`         | Primary model stage to load               |
| `fallback_stage`            | --      | `str`   | `"Staging"`            | Fallback stage if primary unavailable     |
| `reload_interval_seconds`   | --      | `int`   | `300`                  | Interval for checking model updates (5 min) |
| `prediction_timeout_seconds` | --     | `float` | `1.0`                 | Timeout for model prediction              |

### Feature Specification

Expected input features for the ML model:

| Feature                   | Type    | Description                                |
|---------------------------|---------|--------------------------------------------|
| `amount`                  | `float` | Transaction amount                         |
| `amount_zscore`           | `float` | Z-score of amount vs user baseline         |
| `hour_of_day`             | `int`   | Hour (0-23) of the transaction             |
| `day_of_week`             | `int`   | Day of week (0=Monday, 6=Sunday)           |
| `tx_type_encoded`         | `int`   | Encoded transaction type                   |
| `balance_delta_sender`    | `float` | Sender balance change                      |
| `balance_delta_receiver`  | `float` | Receiver balance change                    |
| `velocity_count_1h`       | `int`   | Transaction count in past 1 hour           |
| `velocity_count_24h`      | `int`   | Transaction count in past 24 hours         |
| `velocity_amount_1h`      | `float` | Transaction amount sum in past 1 hour      |
| `velocity_amount_24h`     | `float` | Transaction amount sum in past 24 hours    |

### Scoring Thresholds

| Parameter    | Env Var | Type    | Default | Description                                  |
|--------------|---------|---------|---------|----------------------------------------------|
| `low_max`    | --      | `float` | `0.3`   | Max score for "low" risk classification      |
| `medium_max` | --      | `float` | `0.6`   | Max score for "medium" risk classification   |
| `high_max`   | --      | `float` | `0.8`   | Max score for "high" (above = "critical")    |

### Hybrid Scoring Configuration

| Parameter     | Env Var | Type    | Default              | Description                                  |
|---------------|---------|---------|----------------------|----------------------------------------------|
| `strategy`    | --      | `str`   | `"weighted_average"` | Scoring strategy: `weighted_average`, `max`, or `ensemble_vote` |
| `rule_weight` | --      | `float` | `0.6`                | Weight for rule-based score in hybrid        |
| `ml_weight`   | --      | `float` | `0.4`                | Weight for ML model score in hybrid          |
| `ml_enabled`  | --      | `bool`  | `True`               | Whether ML scoring is active                 |

Hybrid scoring strategies:
- **`weighted_average`**: `score = rule_weight * rule_score + ml_weight * ml_score`
- **`max`**: `score = max(rule_score, ml_score)`
- **`ensemble_vote`**: Both scores must agree above threshold to flag
