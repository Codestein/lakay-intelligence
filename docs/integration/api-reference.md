# Lakay Intelligence — API Reference

Complete reference for every Lakay Intelligence API endpoint. Organized by domain.

**Base URL**: `http://localhost:8000` (configurable via `HOST` and `PORT` environment variables)
**Content Type**: All endpoints accept and return `application/json`
**Authentication**: Token-based (to be configured at integration time; currently unauthenticated)
**Pagination**: List endpoints support `limit` (default 50, max 500) and `offset` (default 0)

---

## Health & Readiness

### GET /health

Health check endpoint. No authentication required.

**Response (200)**:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3600
}
```

### GET /ready

Dependency readiness check. No authentication required. Returns 200 when all dependencies are available, 503 when degraded.

**Response (200)**:
```json
{
  "status": "ready",
  "kafka": false,
  "database": true,
  "redis": true
}
```

---

## Fraud Detection

### POST /api/v1/fraud/score

Score a transaction for fraud risk using hybrid rules + ML scoring.

**Request Body**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| transaction_id | string | Yes | Unique transaction identifier |
| user_id | string | Yes | User initiating the transaction |
| amount | string | Yes | Transaction amount (decimal string, e.g. "100.00") |
| currency | string | No | Currency code (default: "USD") |
| ip_address | string | No | Client IP address |
| device_id | string | No | Device fingerprint |
| geo_location | object | No | `{latitude, longitude, country, city}` |
| transaction_type | string | No | e.g. "circle_contribution", "remittance_send" |
| initiated_at | datetime | No | ISO 8601 timestamp |
| recipient_id | string | No | Recipient user ID |

**Example Request**:
```json
{
  "transaction_id": "tx-001",
  "user_id": "user-001",
  "amount": "500.00",
  "currency": "USD",
  "ip_address": "10.0.1.50",
  "device_id": "device_abc123",
  "transaction_type": "remittance_send",
  "initiated_at": "2026-01-15T14:00:00Z"
}
```

**Response (200)**:
```json
{
  "transaction_id": "tx-001",
  "score": 15.0,
  "composite_score": 0.15,
  "rule_score": 0.15,
  "ml_score": null,
  "risk_tier": "low",
  "recommendation": "allow",
  "confidence": 0.85,
  "risk_factors": [],
  "model_version": "rules-v2",
  "computed_at": "2026-01-15T14:00:01Z"
}
```

**Error Codes**: 422 (missing required fields or invalid types)

### GET /api/v1/fraud/rules

Return current rule configurations, thresholds, and weights.

**Response (200)**:
```json
{
  "model_version": "rules-v2",
  "rule_count": 12,
  "rules": [
    {"rule_id": "velocity_count_1h", "category": "velocity", "default_weight": 0.8}
  ],
  "category_caps": {"velocity": 0.3, "amount": 0.3, "geo": 0.25, "patterns": 0.15},
  "alert_thresholds": {"high": 60, "critical": 80}
}
```

### GET /api/v1/fraud/alerts

List fraud alerts with filtering and pagination.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| limit | int | 50 | Max results (1-500) |
| offset | int | 0 | Skip N results |
| severity | string | null | Filter: "high", "critical" |
| status | string | null | Filter: "open", "resolved" |
| user_id | string | null | Filter by user |
| risk_tier | string | null | Filter by risk tier |
| date_from | datetime | null | Start date filter |
| date_to | datetime | null | End date filter |
| sort_by | string | "created_at" | "created_at" or "severity" |

**Response (200)**:
```json
{
  "items": [
    {
      "alert_id": "alert-001",
      "user_id": "user-001",
      "alert_type": "fraud",
      "severity": "high",
      "details": {"risk_score": 75, "risk_tier": "high"},
      "status": "open",
      "created_at": "2026-01-15T14:00:00Z",
      "resolved_at": null
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

---

## Model Serving

### POST /api/v1/serving/reload

Trigger hot-reload of the production model from MLflow. Administrative endpoint.

**Response (200)**:
```json
{
  "success": true,
  "model_name": "fraud-detector",
  "model_version": "v0.2",
  "message": "Model reloaded successfully"
}
```

### GET /api/v1/serving/routing

Inspect current A/B routing configuration.

**Response (200)**:
```json
{
  "enabled": false,
  "champion_pct": 95.0,
  "challenger_pct": 5.0,
  "champion_model": "fraud-detector",
  "champion_version": "v0.2",
  "challenger_model": null,
  "challenger_version": null,
  "metrics_summary": {}
}
```

### POST /api/v1/serving/routing

Update A/B traffic split. Administrative endpoint.

**Request Body**:
| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| champion_pct | float | Yes | 0-100 |
| challenger_pct | float | Yes | 0-100 |

**Response (200)**: Same as GET /api/v1/serving/routing with updated values.

### GET /api/v1/serving/monitoring

Model health metrics including scores, latency, and drift.

**Response (200)**:
```json
{
  "model": {
    "name": "fraud-detector",
    "version": "v0.2",
    "loaded": true,
    "load_error": null
  },
  "scores": {},
  "drift": {},
  "timestamp": "2026-01-15T14:00:00Z"
}
```

---

## Circle Health

### POST /api/v1/circles/{circle_id}/score

Compute and return the health score for a circle.

**Path Parameters**: `circle_id` (string)

**Request Body** (optional):
```json
{
  "circle_id": "circle-001",
  "features": {
    "payment_timeliness": 0.95,
    "member_retention": 0.90,
    "contribution_rate": 1.0,
    "dispute_count": 0
  }
}
```

**Response (200)**:
```json
{
  "circle_id": "circle-001",
  "health_score": 85.0,
  "health_tier": "healthy",
  "trend": "stable",
  "confidence": 0.95,
  "dimension_scores": {
    "contribution_reliability": {"dimension_name": "contribution_reliability", "score": 90, "weight": 0.35, "contributing_factors": []}
  },
  "anomaly_count": 0,
  "classification": {
    "tier": "healthy",
    "recommended_actions": [],
    "reason": "All dimensions within healthy range"
  },
  "tier_change": null,
  "scoring_version": "circle-health-v1",
  "computed_at": "2026-01-15T14:00:00Z"
}
```

### GET /api/v1/circles/{circle_id}/health

Retrieve the most recently computed health score for a circle.

**Response (200)**:
```json
{
  "circle_id": "circle-001",
  "health_score": 85.0,
  "health_tier": "healthy",
  "trend": "stable",
  "confidence": 0.95,
  "dimension_scores": {},
  "scoring_version": "circle-health-v1",
  "computed_at": "2026-01-15T14:00:00Z"
}
```

If no score exists: `{"circle_id": "...", "health_score": null, "message": "No health score computed yet for this circle"}`

### GET /api/v1/circles/health/summary

Health scores for all active circles with pagination and filtering.

**Query Parameters**: `tier`, `sort_by` (health_score|computed_at), `sort_order` (asc|desc), `limit`, `offset`

**Response (200)**:
```json
{
  "items": [
    {"circle_id": "circle-001", "health_score": 85.0, "health_tier": "healthy", "trend": "stable", "last_updated": "2026-01-15T14:00:00Z"}
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### GET /api/v1/circles/{circle_id}/anomalies

Detected anomalies for a circle, filterable by type and severity.

**Query Parameters**: `anomaly_type`, `severity`, `limit`, `offset`

**Response (200)**:
```json
{
  "items": [
    {
      "anomaly_id": "anom-001",
      "circle_id": "circle-001",
      "anomaly_type": "coordinated_late",
      "severity": "medium",
      "affected_members": ["user-001", "user-002"],
      "evidence": [{"metric_name": "late_rate", "observed_value": 0.4, "threshold": 0.2, "description": "..."}],
      "detected_at": "2026-01-15T14:00:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### GET /api/v1/circles/{circle_id}/classification

Current risk tier with recommended actions.

**Response (200)**:
```json
{
  "circle_id": "circle-001",
  "health_tier": "at-risk",
  "health_score": 45.0,
  "trend": "deteriorating",
  "anomaly_count": 2,
  "recommended_actions": [{"action": "Contact organizer", "reason": "Multiple late payments", "priority": "high"}],
  "classification_reason": "Health score below at-risk threshold with active anomalies",
  "classified_at": "2026-01-15T14:00:00Z"
}
```

### GET /api/v1/circles/at-risk

All circles classified as At-Risk or Critical, sorted by severity (lowest score first).

**Query Parameters**: `limit`, `offset`

**Response (200)**:
```json
{
  "items": [
    {
      "circle_id": "circle-001",
      "health_tier": "critical",
      "health_score": 25.0,
      "trend": "deteriorating",
      "recommended_actions": [],
      "classified_at": "2026-01-15T14:00:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

---

## Behavioral Analytics

### GET /api/v1/behavior/users/{user_id}/profile

Full behavioral profile with maturity status.

**Response (200)**:
```json
{
  "user_id": "user-001",
  "profile_status": "active",
  "profile_maturity": 35,
  "session_baseline": {"avg_duration": 300.0, "std_duration": 120.0, "avg_actions": 15.0, "std_actions": 5.0, "typical_action_sequences": []},
  "temporal_baseline": {"typical_hours": {"14": 0.3, "15": 0.2}, "typical_days": {}, "typical_frequency_mean": 3.5, "typical_frequency_std": 1.2},
  "device_baseline": {"known_devices": ["device_abc"], "primary_device": "device_abc", "device_switch_rate": 0.1, "device_platforms": ["ios"]},
  "geographic_baseline": {"known_locations": [{"city": "Boston", "country": "US"}], "primary_location": {"city": "Boston", "country": "US"}, "typical_travel_patterns": []},
  "engagement_baseline": {"typical_features_used": ["send_money", "check_balance"], "feature_usage_breadth": 0.4, "avg_sessions_per_week": 3.5},
  "last_updated": "2026-01-15T14:00:00Z",
  "profile_version": "behavior-profile-v1"
}
```

If no profile: `{"user_id": "...", "profile": null, "message": "No behavioral profile found for this user"}`

### GET /api/v1/behavior/users/{user_id}/profile/summary

Simplified profile view.

**Response (200)**:
```json
{
  "user_id": "user-001",
  "profile_status": "active",
  "profile_maturity": 35,
  "primary_device": "device_abc",
  "primary_location": {"city": "Boston", "country": "US"},
  "typical_hours": "Peak hours: 14, 15, 10:00",
  "risk_level": "low",
  "last_updated": "2026-01-15T14:00:00Z"
}
```

### POST /api/v1/behavior/sessions/score

Score a session for anomalies in real-time.

**Request Body**:
| Field | Type | Required |
|-------|------|----------|
| session_id | string | Yes |
| user_id | string | Yes |
| device_id | string | No |
| device_type | string | No |
| ip_address | string | No |
| geo_location | object | No |
| session_start | datetime | No |
| session_duration_seconds | float | No |
| action_count | int | No |
| actions | list[string] | No |
| features | dict | No |

**Response (200)**:
```json
{
  "session_id": "sess-001",
  "user_id": "user-001",
  "composite_score": 0.15,
  "classification": "normal",
  "dimension_scores": [{"dimension": "temporal", "score": 0.1, "details": "Within normal hours"}],
  "profile_maturity": 0,
  "recommended_action": "none",
  "timestamp": "2026-01-15T14:00:00Z"
}
```

### GET /api/v1/behavior/users/{user_id}/engagement

Engagement score, lifecycle stage, and churn risk.

**Response (200)**:
```json
{
  "user_id": "user-001",
  "engagement_score": 72.0,
  "lifecycle_stage": "active",
  "churn_risk": 0.15,
  "churn_risk_level": "low",
  "engagement_trend": "stable",
  "computed_at": "2026-01-15T14:00:00Z"
}
```

### GET /api/v1/behavior/engagement/summary

Distribution of users across lifecycle stages.

**Response (200)**:
```json
{
  "total_users": 0,
  "stage_distribution": {},
  "avg_engagement_by_stage": {},
  "message": "Query individual users via /users/{user_id}/engagement. Batch summary requires aggregated data."
}
```

### GET /api/v1/behavior/engagement/at-risk

Users with high churn risk.

**Response (200)**:
```json
{
  "items": [],
  "total": 0,
  "message": "At-risk users are identified during engagement scoring. Query individual users to check churn risk."
}
```

### POST /api/v1/behavior/ato/assess

ATO risk assessment for a session.

**Request Body**:
| Field | Type | Required |
|-------|------|----------|
| session_id | string | Yes |
| user_id | string | Yes |
| device_id | string | No |
| device_type | string | No |
| ip_address | string | No |
| geo_location | object | No |
| session_start | datetime | No |
| session_duration_seconds | float | No |
| action_count | int | No |
| actions | list[string] | No |
| failed_login_count_10m | int | No (default 0) |
| failed_login_count_1h | int | No (default 0) |
| pending_transactions | list[string] | No |
| features | dict | No |

**Response (200)**:
```json
{
  "session_id": "sess-001",
  "user_id": "user-001",
  "ato_risk_score": 0.85,
  "risk_level": "high",
  "contributing_signals": [{"signal_name": "failed_logins", "score": 0.9, "details": "5 failed attempts in 10 minutes"}],
  "recommended_response": "step_up_auth",
  "affected_transactions": [],
  "timestamp": "2026-01-15T14:00:00Z"
}
```

### GET /api/v1/behavior/ato/alerts

List ATO alerts with filtering.

**Query Parameters**: `user_id`, `status`, `risk_level`, `start_date`, `end_date`, `limit`, `offset`

**Response (200)**:
```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

### PUT /api/v1/behavior/ato/alerts/{alert_id}

Update ATO alert status.

**Request Body**: `{"status": "investigating"}` — Valid values: new, investigating, confirmed_ato, false_positive, resolved

**Response (200)**: Updated alert object or `{"alert_id": "...", "message": "ATO alert not found"}`

---

## Compliance Intelligence

### GET /api/v1/compliance/ctr/daily/{user_id}

Current business day cumulative total for a user.

**Response (200)**:
```json
{
  "user_id": "user-001",
  "business_date": "2026-01-15",
  "cumulative_amount": 0.0,
  "transaction_count": 0,
  "transaction_ids": [],
  "threshold_met": false,
  "alert_generated": false,
  "ctr_threshold": 10000.0
}
```

### GET /api/v1/compliance/ctr/pending

All users with pending CTR obligations.

**Response (200)**:
```json
{
  "items": [
    {
      "package_id": "pkg-001",
      "user_id": "user-001",
      "business_date": "2026-01-15",
      "total_amount": 12000.00,
      "transaction_count": 3,
      "status": "pending",
      "assembled_at": "2026-01-15T14:00:00Z",
      "filing_deadline": "2026-01-30"
    }
  ],
  "total": 1
}
```

### GET /api/v1/compliance/ctr/filings

CTR filing history with status.

**Response (200)**:
```json
{
  "items": [],
  "total": 0
}
```

### GET /api/v1/compliance/alerts

All compliance alerts, filterable.

**Query Parameters**: `alert_type`, `priority`, `status`, `user_id`, `limit`, `offset`

Valid `alert_type` values: ctr_threshold, structuring, suspicious_activity, ofac_match, edd_trigger, velocity_anomaly
Valid `priority` values: routine, elevated, urgent, critical
Valid `status` values: new, under_review, filed, dismissed_with_rationale, escalated

**Response (200)**:
```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

### PUT /api/v1/compliance/alerts/{alert_id}

Update alert status with review notes.

**Request Body**:
```json
{
  "status": "under_review",
  "reviewed_by": "analyst-001",
  "resolution_notes": "Reviewing transaction patterns"
}
```

**Response (200)**: Updated alert object.

### GET /api/v1/compliance/cases

Compliance cases, filterable.

**Query Parameters**: `status`, `user_id`, `limit`, `offset`

**Response (200)**:
```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

### POST /api/v1/compliance/cases

Create a compliance case from grouped alerts.

**Request Body**:
```json
{
  "user_id": "user-001",
  "alert_ids": ["alert-001", "alert-002"],
  "case_type": "structuring",
  "assigned_to": "analyst-001"
}
```

**Response (200)**: Created case object with `case_id`, `status: "open"`, `opened_at`.

### PUT /api/v1/compliance/cases/{case_id}

Update case status.

**Request Body**:
```json
{
  "status": "investigating",
  "assigned_to": "analyst-001",
  "filing_reference": null,
  "narrative": null
}
```

Valid `status` values: open, investigating, pending_filing, filed, closed

### POST /api/v1/compliance/sar/draft/{case_id}

Generate a SAR narrative draft for a case.

**Response (200)**:
```json
{
  "draft_id": "draft-001",
  "case_id": "case-001",
  "user_id": "user-001",
  "narrative": "Based on the analysis of...",
  "sections": {},
  "confidence_note": "",
  "status": "draft",
  "generated_at": "2026-01-15T14:00:00Z",
  "reviewed_at": null,
  "reviewed_by": null,
  "machine_generated_disclaimer": "MACHINE-GENERATED DRAFT — ..."
}
```

### GET /api/v1/compliance/sar/drafts

List all pending SAR drafts.

**Response (200)**: `{"items": [...], "total": N}`

### PUT /api/v1/compliance/sar/drafts/{draft_id}

Update SAR draft status.

**Request Body**: `{"status": "reviewed", "reviewed_by": "analyst-001"}`

Valid `status` values: draft, reviewed, approved, filed, rejected

### GET /api/v1/compliance/risk/{user_id}

Current customer risk profile with all contributing factors.

**Response (200)**:
```json
{
  "user_id": "user-001",
  "risk_level": "low",
  "risk_score": 0.0,
  "risk_factors": [],
  "edd_required": false,
  "message": "No risk assessment on record. Run POST /risk/{user_id}/review to assess."
}
```

### GET /api/v1/compliance/risk/high

All high-risk and prohibited customers.

**Response (200)**: `{"items": [...], "total": N}`

### GET /api/v1/compliance/risk/{user_id}/history

Risk score history over time.

**Response (200)**: `{"items": [...], "total": N}`

### POST /api/v1/compliance/risk/{user_id}/review

Record a compliance officer's review of a customer's risk level.

**Request Body**:
```json
{
  "reviewer": "analyst-001",
  "notes": "Annual review completed",
  "new_risk_level": "medium"
}
```

Valid `new_risk_level` values: low, medium, high, prohibited

---

## Data Pipeline

### GET /api/v1/pipeline/bronze/stats

Bronze layer ingestion statistics.

**Response (200)**:
```json
{
  "total_events_ingested": 0,
  "events_by_type": {},
  "partitions_created": 0,
  "total_size_bytes": 0,
  "latest_checkpoints": {}
}
```

### GET /api/v1/pipeline/bronze/partitions

List bronze partitions with metadata.

**Query Parameters**: `event_type`, `start_date` (ISO 8601), `end_date` (ISO 8601)

**Response (200)**: `{"partitions": [...], "count": N}`

### GET /api/v1/pipeline/silver/stats

Silver processing statistics.

**Response (200)**:
```json
{
  "total_processed": 0,
  "total_passed": 0,
  "total_rejected": 0,
  "total_deduplicated": 0,
  "by_event_type": {}
}
```

### GET /api/v1/pipeline/silver/quality

Latest quality check results per event type.

**Query Parameters**: `event_type`

**Response (200)**: `{"quality_results": [...]}`

### GET /api/v1/pipeline/silver/rejected

Sample of rejected events with rejection reasons.

**Query Parameters**: `event_type`, `limit` (1-100, default 10)

**Response (200)**: `{"rejected_events": [...], "count": N}`

### GET /api/v1/pipeline/gold/datasets

List available gold datasets with freshness timestamps.

**Response (200)**: `{"datasets": [...]}`

### GET /api/v1/pipeline/gold/{dataset_name}

Query a gold dataset with optional filters.

**Query Parameters**: `start_date`, `end_date`, `limit` (1-1000, default 100)

**Response (200)**:
```json
{
  "dataset": "daily-transaction-summary",
  "records": [],
  "total_count": 0,
  "returned_count": 0
}
```

### POST /api/v1/pipeline/gold/{dataset_name}/refresh

Trigger on-demand refresh of a gold dataset. Administrative endpoint.

**Response (200)**: Refresh result with status and record count.

---

## Experiments

### POST /api/v1/experiments

Create a new A/B experiment. Administrative endpoint.

**Request Body**:
```json
{
  "name": "fraud-threshold-test",
  "description": "Test lower fraud threshold",
  "hypothesis": "Lower threshold reduces false negatives",
  "variants": [
    {"variant_id": "control", "name": "control", "config": {"threshold": 60}},
    {"variant_id": "treatment", "name": "treatment", "config": {"threshold": 45}}
  ],
  "assignment_strategy": "user_hash",
  "traffic_allocation": {"control": 0.5, "treatment": 0.5},
  "primary_metric": "fraud_detection_rate",
  "guardrail_metrics": ["false_positive_rate"]
}
```

**Response (200)**: Created experiment with `experiment_id` and `status: "draft"`.

### GET /api/v1/experiments

List experiments, optionally filtered by status.

**Query Parameters**: `status` (draft, running, paused, completed, cancelled)

**Response (200)**:
```json
{
  "experiments": [],
  "count": 0
}
```

### GET /api/v1/experiments/{experiment_id}

Get experiment details.

**Response (200)**: Full experiment object or `{"error": "experiment_not_found"}`.

### PUT /api/v1/experiments/{experiment_id}/start

Start an experiment. Changes status from draft to running.

### PUT /api/v1/experiments/{experiment_id}/pause

Pause a running experiment.

### PUT /api/v1/experiments/{experiment_id}/complete

Complete an experiment and generate final report.

### GET /api/v1/experiments/{experiment_id}/results

Get statistical analysis results for an experiment.

**Response (200)**: Significance results, metric summaries, and recommendation.

### GET /api/v1/experiments/{experiment_id}/guardrails

Get guardrail check status for an experiment.

**Response (200)**:
```json
{
  "guardrails": [],
  "any_breached": false
}
```

---

## Dashboards

### GET /api/v1/dashboards/platform

Platform health overview dashboard.

**Query Parameters**: `start_date`, `end_date`

### GET /api/v1/dashboards/fraud

Fraud operations overview dashboard.

**Query Parameters**: `start_date`, `end_date`

### GET /api/v1/dashboards/circles

Circle health overview dashboard.

### GET /api/v1/dashboards/compliance

Compliance overview dashboard.

**Query Parameters**: `start_date`, `end_date`

### GET /api/v1/dashboards/corridor

Haiti corridor analytics dashboard.

**Query Parameters**: `start_date`, `end_date`

---

## Compliance Reports

### POST /api/v1/pipeline/compliance-reports/ctr

Generate CTR report for a date range.

**Request Body**:
```json
{
  "start_date": "2026-01-01T00:00:00",
  "end_date": "2026-01-31T23:59:59"
}
```

**Response (200)**:
```json
{
  "report_id": "ctr_abc123",
  "report_type": "ctr",
  "date_range": {"start": "...", "end": "..."},
  "transactions": [],
  "summary": {"total_transactions": 0, "total_amount": 0.0, "filing_count": 0},
  "generated_at": "2026-01-15T14:00:00Z"
}
```

### POST /api/v1/pipeline/compliance-reports/sar

Generate SAR report for a date range.

**Request Body**: `{"start_date": "...", "end_date": "..."}`

**Response (200)**:
```json
{
  "report_id": "sar_abc123",
  "report_type": "sar",
  "date_range": {"start": "...", "end": "..."},
  "cases": [],
  "narratives": [],
  "summary": {"total_cases": 0, "narratives_generated": 0},
  "generated_at": "2026-01-15T14:00:00Z"
}
```

### POST /api/v1/pipeline/compliance-reports/summary

Generate compliance summary.

**Request Body**: `{"period": "monthly"}`

**Response (200)**: Summary with alert_volume, case_dispositions, filing_counts, risk_distribution.

### POST /api/v1/pipeline/compliance-reports/audit

Generate audit readiness report.

**Request Body**: `{"start_date": "...", "end_date": "..."}`

**Response (200)**: Report with monitoring_rules, alert_statistics, filing_timeliness, system_uptime, model_governance.

### GET /api/v1/pipeline/compliance-reports

List generated compliance reports.

**Query Parameters**: `report_type`, `start_date`, `end_date`

**Response (200)**: `{"reports": [...], "count": N}`

### GET /api/v1/pipeline/compliance-reports/{report_id}

Retrieve a specific generated report.

**Response (200)**: Full report object or `{"error": "report_not_found"}`.

---

## Common Error Responses

### 422 Validation Error

Returned when request body fails Pydantic validation.

```json
{
  "detail": [
    {
      "loc": ["body", "transaction_id"],
      "msg": "Field required",
      "type": "missing"
    }
  ]
}
```

### 404 Not Found

Returned for unknown routes.

### 405 Method Not Allowed

Returned when using wrong HTTP method on an endpoint.

### 500 Internal Server Error

```json
{
  "detail": "Internal server error"
}
```

---

## Endpoint Inventory

| # | Method | Path | Domain |
|---|--------|------|--------|
| 1 | GET | /health | Health |
| 2 | GET | /ready | Health |
| 3 | POST | /api/v1/fraud/score | Fraud |
| 4 | GET | /api/v1/fraud/rules | Fraud |
| 5 | GET | /api/v1/fraud/alerts | Fraud |
| 6 | POST | /api/v1/serving/reload | Serving |
| 7 | GET | /api/v1/serving/routing | Serving |
| 8 | POST | /api/v1/serving/routing | Serving |
| 9 | GET | /api/v1/serving/monitoring | Serving |
| 10 | POST | /api/v1/circles/{circle_id}/score | Circles |
| 11 | GET | /api/v1/circles/{circle_id}/health | Circles |
| 12 | GET | /api/v1/circles/health/summary | Circles |
| 13 | GET | /api/v1/circles/{circle_id}/anomalies | Circles |
| 14 | GET | /api/v1/circles/{circle_id}/classification | Circles |
| 15 | GET | /api/v1/circles/at-risk | Circles |
| 16 | GET | /api/v1/behavior/users/{user_id}/profile | Behavior |
| 17 | GET | /api/v1/behavior/users/{user_id}/profile/summary | Behavior |
| 18 | POST | /api/v1/behavior/sessions/score | Behavior |
| 19 | GET | /api/v1/behavior/users/{user_id}/engagement | Behavior |
| 20 | GET | /api/v1/behavior/engagement/summary | Behavior |
| 21 | GET | /api/v1/behavior/engagement/at-risk | Behavior |
| 22 | POST | /api/v1/behavior/ato/assess | Behavior |
| 23 | GET | /api/v1/behavior/ato/alerts | Behavior |
| 24 | PUT | /api/v1/behavior/ato/alerts/{alert_id} | Behavior |
| 25 | GET | /api/v1/compliance/ctr/daily/{user_id} | Compliance |
| 26 | GET | /api/v1/compliance/ctr/pending | Compliance |
| 27 | GET | /api/v1/compliance/ctr/filings | Compliance |
| 28 | GET | /api/v1/compliance/alerts | Compliance |
| 29 | PUT | /api/v1/compliance/alerts/{alert_id} | Compliance |
| 30 | GET | /api/v1/compliance/cases | Compliance |
| 31 | POST | /api/v1/compliance/cases | Compliance |
| 32 | PUT | /api/v1/compliance/cases/{case_id} | Compliance |
| 33 | POST | /api/v1/compliance/sar/draft/{case_id} | Compliance |
| 34 | GET | /api/v1/compliance/sar/drafts | Compliance |
| 35 | PUT | /api/v1/compliance/sar/drafts/{draft_id} | Compliance |
| 36 | GET | /api/v1/compliance/risk/{user_id} | Compliance |
| 37 | GET | /api/v1/compliance/risk/high | Compliance |
| 38 | GET | /api/v1/compliance/risk/{user_id}/history | Compliance |
| 39 | POST | /api/v1/compliance/risk/{user_id}/review | Compliance |
| 40 | GET | /api/v1/pipeline/bronze/stats | Pipeline |
| 41 | GET | /api/v1/pipeline/bronze/partitions | Pipeline |
| 42 | GET | /api/v1/pipeline/silver/stats | Pipeline |
| 43 | GET | /api/v1/pipeline/silver/quality | Pipeline |
| 44 | GET | /api/v1/pipeline/silver/rejected | Pipeline |
| 45 | GET | /api/v1/pipeline/gold/datasets | Pipeline |
| 46 | GET | /api/v1/pipeline/gold/{dataset_name} | Pipeline |
| 47 | POST | /api/v1/pipeline/gold/{dataset_name}/refresh | Pipeline |
| 48 | POST | /api/v1/experiments | Experiments |
| 49 | GET | /api/v1/experiments | Experiments |
| 50 | GET | /api/v1/experiments/{id} | Experiments |
| 51 | PUT | /api/v1/experiments/{id}/start | Experiments |
| 52 | PUT | /api/v1/experiments/{id}/pause | Experiments |
| 53 | PUT | /api/v1/experiments/{id}/complete | Experiments |
| 54 | GET | /api/v1/experiments/{id}/results | Experiments |
| 55 | GET | /api/v1/experiments/{id}/guardrails | Experiments |
| 56 | GET | /api/v1/dashboards/platform | Dashboards |
| 57 | GET | /api/v1/dashboards/fraud | Dashboards |
| 58 | GET | /api/v1/dashboards/circles | Dashboards |
| 59 | GET | /api/v1/dashboards/compliance | Dashboards |
| 60 | GET | /api/v1/dashboards/corridor | Dashboards |
| 61 | POST | /api/v1/pipeline/compliance-reports/ctr | Reports |
| 62 | POST | /api/v1/pipeline/compliance-reports/sar | Reports |
| 63 | POST | /api/v1/pipeline/compliance-reports/summary | Reports |
| 64 | POST | /api/v1/pipeline/compliance-reports/audit | Reports |
| 65 | GET | /api/v1/pipeline/compliance-reports | Reports |
| 66 | GET | /api/v1/pipeline/compliance-reports/{id} | Reports |
