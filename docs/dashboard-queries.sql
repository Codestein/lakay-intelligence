-- ==========================================================================
-- Lakay Intelligence — Dashboard SQL Queries
-- ==========================================================================
-- These queries are the SQL equivalents of the Python dashboard functions
-- in src/pipeline/dashboards.py. They can be run against:
--   - Gold layer Parquet files via DuckDB (local dev)
--   - PostgreSQL if gold data is materialized there
--
-- Gold datasets are stored at:
--   lakay-data-lake/gold/{dataset_name}/{year}/{month}/{day}/*.parquet
-- ==========================================================================

-- ==========================================================================
-- G-1: Daily Transaction Summary
-- Dataset: daily-transaction-summary
-- Grain: per-user, per-day
-- ==========================================================================

-- Query: Platform-wide daily transaction volume
-- Purpose: Powers the platform overview dashboard transaction metrics
SELECT
    date,
    SUM(transaction_count) AS total_transactions,
    SUM(total_amount)      AS total_volume,
    AVG(average_amount)    AS avg_transaction_amount,
    COUNT(DISTINCT user_id) AS unique_transacting_users
FROM read_parquet('s3://lakay-data-lake/gold/daily-transaction-summary/**/*.parquet')
WHERE date BETWEEN :start_date AND :end_date
GROUP BY date
ORDER BY date;

-- Query: Top users by transaction volume (30-day)
-- Purpose: Identifies high-volume users for compliance review
SELECT
    user_id,
    SUM(transaction_count)    AS total_transactions,
    SUM(total_amount)         AS total_volume,
    AVG(average_amount)       AS avg_amount,
    MAX(max_amount)           AS largest_single_transaction,
    SUM(distinct_recipients)  AS total_distinct_recipients
FROM read_parquet('s3://lakay-data-lake/gold/daily-transaction-summary/**/*.parquet')
WHERE date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY user_id
ORDER BY total_volume DESC
LIMIT 50;


-- ==========================================================================
-- G-2: Circle Lifecycle Summary
-- Dataset: circle-lifecycle-summary
-- Grain: per-circle
-- ==========================================================================

-- Query: Circle health distribution
-- Purpose: Powers the circle health dashboard tier distribution
SELECT
    current_tier,
    COUNT(*)                     AS circle_count,
    AVG(health_score)            AS avg_health_score,
    AVG(member_count_current)    AS avg_current_members,
    AVG(collection_ratio)        AS avg_collection_ratio
FROM read_parquet('s3://lakay-data-lake/gold/circle-lifecycle-summary/**/*.parquet')
GROUP BY current_tier
ORDER BY current_tier;

-- Query: At-risk and critical circles
-- Purpose: Surfaces circles needing intervention
SELECT
    circle_id,
    current_tier,
    health_score,
    member_count_original,
    member_count_current,
    member_count_dropped,
    collection_ratio,
    days_active
FROM read_parquet('s3://lakay-data-lake/gold/circle-lifecycle-summary/**/*.parquet')
WHERE current_tier IN ('at_risk', 'critical')
ORDER BY health_score ASC;


-- ==========================================================================
-- G-3: User Risk Dashboard
-- Dataset: user-risk-dashboard
-- Grain: per-user
-- ==========================================================================

-- Query: High-risk users
-- Purpose: Powers the user risk dashboard, identifying users needing review
SELECT
    user_id,
    fraud_score,
    compliance_risk_level,
    engagement_stage,
    ato_alert_count,
    compliance_alert_count,
    txn_volume_7d,
    txn_volume_30d,
    circle_participation_count
FROM read_parquet('s3://lakay-data-lake/gold/user-risk-dashboard/**/*.parquet')
WHERE fraud_score > 0.6
   OR compliance_risk_level IN ('high', 'critical')
   OR ato_alert_count > 0
ORDER BY fraud_score DESC;

-- Query: User risk distribution
-- Purpose: Aggregate risk profile of the user base
SELECT
    compliance_risk_level,
    COUNT(*)                    AS user_count,
    AVG(fraud_score)            AS avg_fraud_score,
    AVG(txn_volume_30d)         AS avg_30d_volume,
    SUM(ato_alert_count)        AS total_ato_alerts,
    SUM(compliance_alert_count) AS total_compliance_alerts
FROM read_parquet('s3://lakay-data-lake/gold/user-risk-dashboard/**/*.parquet')
GROUP BY compliance_risk_level
ORDER BY compliance_risk_level;


-- ==========================================================================
-- G-4: Compliance Reporting
-- Dataset: compliance-reporting
-- Grain: per-day, per-metric
-- ==========================================================================

-- Query: CTR filing summary
-- Purpose: BSA officer dashboard — CTR filing volume and amounts
SELECT
    date,
    ctr_filing_count,
    ctr_total_amount,
    sar_filing_count,
    edd_reviews_due
FROM read_parquet('s3://lakay-data-lake/gold/compliance-reporting/**/*.parquet')
WHERE date BETWEEN :start_date AND :end_date
ORDER BY date;

-- Query: Monthly compliance totals
-- Purpose: Monthly compliance summary for regulatory reporting
SELECT
    DATE_TRUNC('month', CAST(date AS DATE)) AS month,
    SUM(ctr_filing_count)                   AS monthly_ctr_filings,
    SUM(ctr_total_amount)                   AS monthly_ctr_amount,
    SUM(sar_filing_count)                   AS monthly_sar_filings,
    SUM(edd_reviews_due)                    AS monthly_edd_reviews
FROM read_parquet('s3://lakay-data-lake/gold/compliance-reporting/**/*.parquet')
GROUP BY DATE_TRUNC('month', CAST(date AS DATE))
ORDER BY month;


-- ==========================================================================
-- G-5: Platform Health
-- Dataset: platform-health
-- Grain: per-day
-- ==========================================================================

-- Query: Daily platform metrics
-- Purpose: Powers the platform overview dashboard
SELECT
    date,
    active_users,
    sessions,
    transaction_count,
    transaction_volume,
    remittance_count,
    remittance_volume,
    circles_created,
    circles_active,
    avg_fraud_score,
    avg_circle_health
FROM read_parquet('s3://lakay-data-lake/gold/platform-health/**/*.parquet')
WHERE date BETWEEN :start_date AND :end_date
ORDER BY date;

-- Query: Weekly trend comparison
-- Purpose: Week-over-week growth metrics
SELECT
    DATE_TRUNC('week', CAST(date AS DATE))  AS week,
    SUM(active_users)                       AS weekly_active_users,
    SUM(sessions)                           AS weekly_sessions,
    SUM(transaction_count)                  AS weekly_transactions,
    SUM(transaction_volume)                 AS weekly_txn_volume,
    SUM(remittance_count)                   AS weekly_remittances,
    SUM(remittance_volume)                  AS weekly_remittance_volume
FROM read_parquet('s3://lakay-data-lake/gold/platform-health/**/*.parquet')
GROUP BY DATE_TRUNC('week', CAST(date AS DATE))
ORDER BY week;


-- ==========================================================================
-- G-6: Haiti Corridor Analytics
-- Dataset: haiti-corridor-analytics
-- Grain: per-day, per-corridor-segment
-- ==========================================================================

-- Query: Corridor volume summary
-- Purpose: Haiti corridor dashboard — volume by corridor
SELECT
    corridor,
    SUM(remittance_count)       AS total_remittances,
    SUM(total_volume_usd)       AS total_volume,
    AVG(average_amount)         AS avg_amount,
    AVG(average_exchange_rate)  AS avg_exchange_rate,
    AVG(delivery_success_rate)  AS avg_delivery_success_rate
FROM read_parquet('s3://lakay-data-lake/gold/haiti-corridor-analytics/**/*.parquet')
WHERE date BETWEEN :start_date AND :end_date
GROUP BY corridor
ORDER BY total_volume DESC;

-- Query: Daily corridor trends
-- Purpose: Time-series view of corridor activity
SELECT
    date,
    corridor,
    remittance_count,
    total_volume_usd,
    average_amount,
    average_exchange_rate,
    delivery_success_rate
FROM read_parquet('s3://lakay-data-lake/gold/haiti-corridor-analytics/**/*.parquet')
WHERE date BETWEEN :start_date AND :end_date
ORDER BY date, corridor;

-- Query: Exchange rate trends per corridor
-- Purpose: Monitor exchange rate movements (compliance + business)
SELECT
    date,
    corridor,
    average_exchange_rate,
    LAG(average_exchange_rate) OVER (
        PARTITION BY corridor ORDER BY date
    ) AS prev_day_rate,
    average_exchange_rate - LAG(average_exchange_rate) OVER (
        PARTITION BY corridor ORDER BY date
    ) AS rate_change
FROM read_parquet('s3://lakay-data-lake/gold/haiti-corridor-analytics/**/*.parquet')
WHERE date BETWEEN :start_date AND :end_date
ORDER BY corridor, date;


-- ==========================================================================
-- Cross-dataset queries (join multiple gold datasets)
-- ==========================================================================

-- Query: High-volume users with elevated risk
-- Purpose: Compliance review — users with high volume AND high risk
SELECT
    t.user_id,
    t.total_volume    AS txn_volume_30d,
    t.total_txns      AS txn_count_30d,
    r.fraud_score,
    r.compliance_risk_level,
    r.ato_alert_count
FROM (
    SELECT
        user_id,
        SUM(total_amount)       AS total_volume,
        SUM(transaction_count)  AS total_txns
    FROM read_parquet('s3://lakay-data-lake/gold/daily-transaction-summary/**/*.parquet')
    WHERE date >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY user_id
) t
JOIN read_parquet('s3://lakay-data-lake/gold/user-risk-dashboard/**/*.parquet') r
    ON t.user_id = r.user_id
WHERE t.total_volume > 5000
  AND (r.fraud_score > 0.5 OR r.compliance_risk_level IN ('high', 'critical'))
ORDER BY t.total_volume DESC;
