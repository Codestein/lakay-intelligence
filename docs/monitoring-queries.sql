-- Monitoring Dashboard Queries for Lakay Intelligence
-- These queries power the model monitoring dashboard.

-- 1. Model accuracy over time (requires ground truth labels)
-- Groups fraud scores by day and model version, showing
-- score distribution for each version.
SELECT
    DATE_TRUNC('day', scored_at) AS day,
    model_version,
    COUNT(*) AS total_scores,
    AVG(risk_score) AS avg_score,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY risk_score) AS median_score,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY risk_score) AS p95_score,
    COUNT(*) FILTER (WHERE risk_tier = 'high' OR risk_tier = 'critical') AS high_risk_count
FROM fraud_scores
GROUP BY DATE_TRUNC('day', scored_at), model_version
ORDER BY day DESC, model_version;


-- 2. Score distributions by risk tier
-- Shows how scores distribute across risk tiers for the current model.
SELECT
    risk_tier,
    COUNT(*) AS count,
    AVG(risk_score) AS avg_score,
    MIN(risk_score) AS min_score,
    MAX(risk_score) AS max_score,
    STDDEV(risk_score) AS stddev_score,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY risk_score) AS median_score
FROM fraud_scores
WHERE scored_at >= NOW() - INTERVAL '7 days'
GROUP BY risk_tier
ORDER BY avg_score DESC;


-- 3. Alert volume by rule (from rules_triggered JSONB)
-- Counts which rules trigger most frequently.
SELECT
    rule_elem->>'rule_name' AS rule_name,
    rule_elem->>'category' AS category,
    COUNT(*) AS trigger_count,
    AVG((rule_elem->>'score')::FLOAT) AS avg_rule_score
FROM fraud_scores,
    LATERAL jsonb_array_elements(rules_triggered->'rules') AS rule_elem
WHERE scored_at >= NOW() - INTERVAL '7 days'
    AND (rule_elem->>'triggered')::BOOLEAN = TRUE
GROUP BY rule_elem->>'rule_name', rule_elem->>'category'
ORDER BY trigger_count DESC;


-- 4. Hourly scoring volume and latency proxy
-- Tracks throughput over time.
SELECT
    DATE_TRUNC('hour', scored_at) AS hour,
    COUNT(*) AS score_count,
    AVG(risk_score) AS avg_score,
    COUNT(*) FILTER (WHERE risk_tier IN ('high', 'critical')) AS flagged_count
FROM fraud_scores
WHERE scored_at >= NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', scored_at)
ORDER BY hour DESC;


-- 5. Model version comparison
-- Compares performance between model versions (rules-v2 vs hybrid).
SELECT
    model_version,
    COUNT(*) AS total,
    AVG(risk_score) AS avg_score,
    AVG(confidence) AS avg_confidence,
    COUNT(*) FILTER (WHERE risk_tier = 'critical') AS critical_count,
    COUNT(*) FILTER (WHERE risk_tier = 'high') AS high_count,
    COUNT(*) FILTER (WHERE risk_tier = 'medium') AS medium_count,
    COUNT(*) FILTER (WHERE risk_tier = 'low') AS low_count
FROM fraud_scores
WHERE scored_at >= NOW() - INTERVAL '7 days'
GROUP BY model_version;


-- 6. Alert trends by severity
SELECT
    DATE_TRUNC('day', created_at) AS day,
    severity,
    COUNT(*) AS alert_count,
    COUNT(*) FILTER (WHERE status = 'open') AS open_count,
    COUNT(*) FILTER (WHERE status = 'resolved') AS resolved_count
FROM alerts
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', created_at), severity
ORDER BY day DESC, severity;


-- 7. Top flagged users (for investigation prioritization)
SELECT
    user_id,
    COUNT(*) AS flag_count,
    AVG(risk_score) AS avg_risk_score,
    MAX(risk_score) AS max_risk_score,
    MAX(scored_at) AS last_flagged
FROM fraud_scores
WHERE risk_tier IN ('high', 'critical')
    AND scored_at >= NOW() - INTERVAL '30 days'
GROUP BY user_id
ORDER BY flag_count DESC
LIMIT 50;


-- 8. Deployment history (for model_deployments table once created)
-- Placeholder: tracks model promotions from the deployment pipeline.
-- CREATE TABLE IF NOT EXISTS model_deployments (
--     id BIGSERIAL PRIMARY KEY,
--     model_name VARCHAR NOT NULL,
--     model_version VARCHAR NOT NULL,
--     previous_version VARCHAR,
--     action VARCHAR NOT NULL,
--     triggered_by VARCHAR NOT NULL,
--     validation_passed BOOLEAN,
--     created_at TIMESTAMPTZ DEFAULT NOW()
-- );
-- SELECT * FROM model_deployments ORDER BY created_at DESC LIMIT 20;
