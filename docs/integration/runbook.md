# Lakay Intelligence -- Trebanx Integration Runbook

> **Phase 10, Task 10.4**
>
> Step-by-step procedure for connecting a Lakay Intelligence instance to a live
> Trebanx platform environment.  Written so any engineer with access to the
> infrastructure can execute it without reverse-engineering code.

---

## Table of Contents

1. [Prerequisites Checklist](#1-prerequisites-checklist)
2. [Phase A -- Environment Setup (Est. 2 hours)](#2-phase-a--environment-setup-est-2-hours)
3. [Phase B -- Schema Alignment (Est. 1-4 hours)](#3-phase-b--schema-alignment-est-1-4-hours)
4. [Phase C -- Kafka Connection (Est. 1 hour)](#4-phase-c--kafka-connection-est-1-hour)
5. [Phase D -- Data Validation (Est. 2-4 hours)](#5-phase-d--data-validation-est-2-4-hours)
6. [Phase E -- Threshold Calibration (Est. 1-2 weeks)](#6-phase-e--threshold-calibration-est-1-2-weeks)
7. [Phase F -- Model Retraining (Est. 1-2 days per cycle)](#7-phase-f--model-retraining-est-1-2-days-per-cycle)
8. [Phase G -- Go-Live](#8-phase-g--go-live)
9. [Troubleshooting Guide](#9-troubleshooting-guide)
10. [Operational Procedures](#10-operational-procedures)

---

## 1. Prerequisites Checklist

Complete every item below before starting Phase A.

### 1.1 Infrastructure Requirements

| Resource   | Minimum          | Recommended (Production) |
|------------|------------------|--------------------------|
| CPU cores  | 4                | 8                        |
| RAM        | 8 GB             | 16 GB                    |
| Disk       | 50 GB SSD        | 200 GB SSD               |
| OS         | Linux (kernel 4.4+) | Ubuntu 22.04 LTS / Amazon Linux 2023 |
| Docker     | 24.0+            | Latest stable            |
| Docker Compose | v2.20+       | Latest stable            |
| Python     | 3.12 (in container) | 3.12                  |

### 1.2 Network Ports

All ports must be reachable from the Lakay host.  In a production VPC, only
port 8000 should be exposed to the upstream Trebanx API gateway; all other
ports remain internal.

| Port  | Service        | Direction               | Notes                               |
|-------|----------------|-------------------------|-------------------------------------|
| 8000  | Lakay API      | Inbound from Trebanx    | HTTP -- health checks, scoring API, dashboards |
| 5432  | PostgreSQL     | Lakay -> Postgres       | Async via asyncpg                   |
| 6379  | Redis          | Lakay -> Redis          | Feature cache, rate limiting        |
| 9092  | Kafka          | Lakay <-> Kafka         | Consumer (inbound events) and Producer (outbound alerts) |
| 9000  | MinIO / S3     | Lakay -> MinIO          | Data lake (bronze/silver/gold layers) |
| 9001  | MinIO Console  | Operator browser        | Optional -- admin UI for object storage |
| 5000  | MLflow         | Lakay -> MLflow         | Model registry, experiment tracking |

### 1.3 External Dependencies

- [ ] **Kafka cluster** -- running and accessible at the configured bootstrap servers
- [ ] **PostgreSQL 16** -- database `lakay` created, user provisioned with full DDL and DML privileges
- [ ] **Redis 7+** -- available and accepting connections
- [ ] **S3-compatible object store** (MinIO or AWS S3) -- bucket `lakay-data-lake` and `mlflow-artifacts` created
- [ ] **MLflow server** -- running, configured to use PostgreSQL as backend store and S3 for artifact storage

### 1.4 Trebanx Readiness

- [ ] **Event producers configured** -- Trebanx services publish to the four required Kafka topics:
  - `trebanx.circle.events`
  - `trebanx.transaction.events`
  - `trebanx.user.events`
  - `trebanx.remittance.events`
- [ ] **Schema versions aligned** -- event payloads match the JSON schemas in the `trebanx-contracts` repository (the same schemas mounted at `CONTRACTS_PATH` inside the Lakay container)
- [ ] **API consumer credentials provisioned** -- if Trebanx calls Lakay's HTTP API directly (e.g., for real-time fraud scoring), an API key or mTLS certificate has been issued
- [ ] **Timezone convention confirmed** -- all event timestamps use ISO 8601 with UTC offset (e.g., `2026-02-27T14:30:00Z`)

---

## 2. Phase A -- Environment Setup (Est. 2 hours)

### 2.1 Clone and Build

```bash
# Clone the repository
git clone <repo-url> lakay-intelligence
cd lakay-intelligence

# Ensure trebanx-contracts is alongside (sibling directory)
git clone <contracts-repo-url> ../trebanx-contracts

# Build the Docker image
docker compose build lakay
```

### 2.2 Create the Production Environment File

Copy the example and customize for production:

```bash
cp .env.example .env
```

Edit `.env` with production values.  The complete reference table follows.

### 2.3 Environment Variable Reference

Every variable recognized by Lakay Intelligence (`src/config.py` and domain
configs).  Values flow through Pydantic Settings; the env file is loaded
automatically.

#### Core Application Settings

| Variable | Purpose | Default | Recommended Production Value |
|----------|---------|---------|------------------------------|
| `APP_NAME` | Service identifier in logs and health endpoint | `lakay-intelligence` | `lakay-intelligence` |
| `APP_VERSION` | Reported in `/health` response | `0.1.0` | Set to actual deployed version |
| `DEBUG` | Enables CORS wildcard, verbose logging | `true` | **`false`** |
| `LOG_LEVEL` | Structlog level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` | `INFO` (use `WARNING` in high-throughput) |
| `HOST` | Bind address for uvicorn | `0.0.0.0` | `0.0.0.0` |
| `PORT` | HTTP listen port | `8000` | `8000` |

#### PostgreSQL

| Variable | Purpose | Default | Recommended Production Value |
|----------|---------|---------|------------------------------|
| `DATABASE_URL` | Async SQLAlchemy connection string | `postgresql+asyncpg://lakay:lakay_dev@localhost:5432/lakay` | `postgresql+asyncpg://<user>:<password>@<host>:5432/lakay` with strong credentials |

#### Kafka

| Variable | Purpose | Default | Recommended Production Value |
|----------|---------|---------|------------------------------|
| `KAFKA_BOOTSTRAP_SERVERS` | Comma-separated broker list | `localhost:9092` | `broker1:9092,broker2:9092,broker3:9092` |
| `KAFKA_CONSUMER_GROUP` | Consumer group ID | `lakay-intelligence` | `lakay-intelligence` (or `lakay-intelligence-<env>`) |
| `KAFKA_AUTO_OFFSET_RESET` | Where to start if no committed offset | `earliest` | `earliest` for initial load, then `latest` in steady state |

#### Redis

| Variable | Purpose | Default | Recommended Production Value |
|----------|---------|---------|------------------------------|
| `REDIS_URL` | Redis connection URI | `redis://localhost:6379/0` | `redis://<host>:6379/0` (use `rediss://` for TLS) |

#### Data Lake (MinIO / S3)

| Variable | Purpose | Default | Recommended Production Value |
|----------|---------|---------|------------------------------|
| `DATALAKE_ENDPOINT` | S3-compatible endpoint URL | `http://localhost:9000` | `https://s3.<region>.amazonaws.com` or MinIO URL |
| `DATALAKE_ACCESS_KEY` | S3 access key | `minioadmin` | IAM role or dedicated service account key |
| `DATALAKE_SECRET_KEY` | S3 secret key | `minioadmin` | Rotated secret, stored in a secrets manager |
| `DATALAKE_BUCKET` | Bucket for bronze/silver/gold data | `lakay-data-lake` | `lakay-data-lake` |

#### PII Protection

| Variable | Purpose | Default | Recommended Production Value |
|----------|---------|---------|------------------------------|
| `PII_TOKEN_SECRET` | HMAC secret for PII tokenization | `lakay-pii-token-secret-dev-only` | **Random 64-char hex string** -- store in secrets manager |
| `PII_ENCRYPTION_KEY` | Symmetric encryption key for PII at rest | `lakay-encryption-key-dev-only` | **Random 32-byte base64** -- store in secrets manager |

#### Contracts

| Variable | Purpose | Default | Recommended Production Value |
|----------|---------|---------|------------------------------|
| `CONTRACTS_PATH` | Path to trebanx-contracts JSON schemas | `../trebanx-contracts/schemas` | `/contracts` (volume-mounted in Docker) |

#### MLflow

| Variable | Purpose | Default | Recommended Production Value |
|----------|---------|---------|------------------------------|
| `MLFLOW_TRACKING_URI` | MLflow server URL | (set in docker-compose) | `http://mlflow:5000` or external MLflow URL |
| `AWS_ACCESS_KEY_ID` | S3 credentials for MLflow artifact store | `minioadmin` | Same as `DATALAKE_ACCESS_KEY` or dedicated key |
| `AWS_SECRET_ACCESS_KEY` | S3 credentials for MLflow artifact store | `minioadmin` | Same as `DATALAKE_SECRET_KEY` or dedicated secret |
| `MLFLOW_S3_ENDPOINT_URL` | S3 endpoint for MLflow artifacts | `http://minio:9000` | Same as `DATALAKE_ENDPOINT` |

#### Fraud Domain Overrides (prefix: `FRAUD_`)

| Variable | Purpose | Default |
|----------|---------|---------|
| `FRAUD_LOGIN_COUNT_MAX` | Max logins in velocity window before flagging | `5` |
| `FRAUD_TXN_COUNT_1H_MAX` | Max transactions in 1 hour | `10` |
| `FRAUD_TXN_AMOUNT_24H_MAX` | Max transaction amount in 24 hours | `10000.0` |
| `FRAUD_LARGE_TXN_MIN` | Minimum amount to classify as "large" | `3000.0` |
| `FRAUD_CTR_SINGLE_THRESHOLD` | Single-transaction CTR trigger | `8000.0` |
| `FRAUD_CTR_DAILY_THRESHOLD` | Daily aggregate CTR trigger | `9000.0` |
| `FRAUD_HIGH_THRESHOLD` | Score threshold for HIGH alert | `0.6` |
| `FRAUD_CRITICAL_THRESHOLD` | Score threshold for CRITICAL alert | `0.8` |
| `FRAUD_ALERT_KAFKA_TOPIC` | Outbound topic for fraud alerts | `lakay.fraud.alerts` |

#### Circle Health Overrides (prefix: `CIRCLE_`)

| Variable | Purpose | Default |
|----------|---------|---------|
| `CIRCLE_CONTRIBUTION_WEIGHT` | Weight for contribution reliability dimension | `0.35` |
| `CIRCLE_MEMBERSHIP_WEIGHT` | Weight for membership stability dimension | `0.25` |
| `CIRCLE_FINANCIAL_WEIGHT` | Weight for financial progress dimension | `0.25` |
| `CIRCLE_TRUST_WEIGHT` | Weight for trust & integrity dimension | `0.15` |
| `CIRCLE_TIER_CHANGE_TOPIC` | Outbound topic for tier change events | `lakay.circles.tier-changes` |

> **Note**: Dimension weights must sum to 1.0. The application validates this at startup and
> will fail with a clear error message if they do not.

#### Behavior Domain Overrides (prefix: `BEHAVIOR_`)

| Variable | Purpose | Default |
|----------|---------|---------|
| `BEHAVIOR_MIN_SESSIONS_ACTIVE` | Minimum sessions before profile is "active" | `10` |
| `BEHAVIOR_EMA_DECAY_RATE` | Exponential moving average decay rate | `0.15` |
| `BEHAVIOR_STALENESS_DAYS` | Days of inactivity before profile goes stale | `30` |
| `BEHAVIOR_TEMPORAL_WEIGHT` | Weight for temporal anomaly dimension | `0.15` |
| `BEHAVIOR_DEVICE_WEIGHT` | Weight for device anomaly dimension | `0.25` |
| `BEHAVIOR_GEO_WEIGHT` | Weight for geographic anomaly dimension | `0.25` |
| `BEHAVIOR_ATO_DEDUP_WINDOW` | ATO alert deduplication window in seconds | `86400` |
| `BEHAVIOR_ATO_KAFKA_TOPIC` | Outbound topic for ATO alerts | `lakay.behavior.ato-alerts` |

#### Compliance Domain Overrides (prefix: `COMPLIANCE_`)

| Variable | Purpose | Default |
|----------|---------|---------|
| `COMPLIANCE_CTR_THRESHOLD` | Currency Transaction Report threshold | `10000.0` |
| `COMPLIANCE_CTR_ENABLED` | Enable/disable CTR monitoring rule | `true` |
| `COMPLIANCE_RAPID_MOVEMENT_HOURS` | Time window for rapid movement detection | `24` |
| `COMPLIANCE_RAPID_MOVEMENT_RATIO` | Transfer ratio threshold for pass-through detection | `0.80` |
| `COMPLIANCE_VOLUME_MULTIPLIER` | Multiplier over 30-day mean to flag unusual volume | `3.0` |
| `COMPLIANCE_STRUCTURING_LOOKBACK_DAYS` | Slow-structuring lookback period | `30` |
| `COMPLIANCE_SAR_CONFIDENCE` | Structuring confidence required to recommend SAR filing | `0.70` |
| `COMPLIANCE_RISK_LOW_MAX` | Upper bound for "low" customer risk score | `0.30` |
| `COMPLIANCE_RISK_HIGH_MAX` | Upper bound for "high" customer risk score | `0.80` |
| `COMPLIANCE_ALERTS_TOPIC` | Outbound topic for compliance alerts | `lakay.compliance.alerts` |
| `COMPLIANCE_EDD_TRIGGERS_TOPIC` | Outbound topic for enhanced due diligence triggers | `lakay.compliance.edd-triggers` |

### 2.4 Docker Deployment

**Option A -- Full stack (for staging or isolated environments):**

```bash
docker compose up -d
```

This starts all seven services: `lakay`, `postgres`, `kafka`, `zookeeper`,
`redis`, `minio` (+ `minio-setup`), and `mlflow`.

**Option B -- Lakay only (connecting to existing infrastructure):**

When PostgreSQL, Kafka, Redis, and S3 are already managed services, run only
the Lakay container:

```bash
docker compose up -d lakay
```

Make sure the `.env` file points all connection strings to the external
services.

### 2.5 Database Migration

Lakay uses Alembic for schema management.  Run migrations inside the
container:

```bash
docker compose exec lakay alembic upgrade head
```

If the database is freshly created, Lakay will also auto-initialize tables
at startup via `init_db()`, but running Alembic explicitly ensures migration
history is recorded.

### 2.6 Health Check Verification

```bash
# Liveness -- should return immediately even if dependencies are still starting
curl -s http://localhost:8000/health | python3 -m json.tool

# Expected response:
# {
#     "status": "healthy",
#     "version": "0.1.0",
#     "uptime_seconds": 12
# }

# Readiness -- checks PostgreSQL and Redis connectivity
curl -s http://localhost:8000/ready | python3 -m json.tool

# Expected response (HTTP 200):
# {
#     "status": "ready",
#     "kafka": false,
#     "database": true,
#     "redis": true
# }
```

If `/ready` returns HTTP 503, check the `database` and `redis` fields to
identify which dependency is unreachable.

> **Checkpoint**: Do not proceed to Phase B until `/ready` returns HTTP 200
> with `database: true` and `redis: true`.

---

## 3. Phase B -- Schema Alignment (Est. 1-4 hours)

### 3.1 Verify Event Producer Schemas

Lakay validates incoming events against the JSON schemas in the
`trebanx-contracts` repository.  The schemas are mounted into the container
at the path specified by `CONTRACTS_PATH` (default: `/contracts`).

List the expected schemas:

```bash
docker compose exec lakay ls /contracts/
```

You should see schema files for the four inbound event types.

### 3.2 Compare Trebanx Producer Schemas

For each event type, retrieve a sample event from the Trebanx producer and
validate it against the contract:

```bash
# From a Kafka console consumer (outside the Lakay stack):
kafka-console-consumer \
  --bootstrap-server <kafka-host>:9092 \
  --topic trebanx.transaction.events \
  --max-messages 1 \
  --from-beginning | python3 -m json.tool
```

Compare the output against the corresponding schema file.  Key fields to
verify:

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `event_id` | Yes | string (UUID) | Unique per event; used for idempotent deduplication |
| `event_type` | Yes | string | Must exactly match a registered handler (e.g., `transaction-initiated`) |
| `event_version` | Yes | string | Schema version (e.g., `1.0`) |
| `timestamp` | Yes | string (ISO 8601) | UTC timezone required |
| `source_service` | Yes | string | Originating Trebanx service name |
| `correlation_id` | No | string (UUID) | Used for distributed tracing |
| `payload` | Yes | object | Domain-specific data; varies by event type |

### 3.3 Expected Event Types per Topic

**`trebanx.circle.events`:**
- `circle-created`
- `circle-member-joined`
- `circle-member-dropped`
- `circle-contribution-received`
- `circle-contribution-missed`
- `circle-payout-executed`
- `circle-completed`
- `circle-failed`

**`trebanx.transaction.events`:**
- `transaction-initiated`
- `transaction-completed`
- `transaction-failed`
- `transaction-flagged`

**`trebanx.user.events`:**
- `user-registered`
- `user-verified`
- `user-profile-updated`
- `login-attempt`
- `login-success`
- `login-failed`
- `session-started`
- `session-ended`
- `device-registered`
- `user-action-performed`

**`trebanx.remittance.events`:**
- `remittance-initiated`
- `remittance-processing`
- `remittance-completed`
- `remittance-failed`
- `exchange-rate-updated`

### 3.4 Schema Version Compatibility Check

Lakay tracks schema versions in its internal schema registry (PostgreSQL
table).  Query it:

```bash
curl -s http://localhost:8000/api/v1/pipeline/bronze/stats | python3 -m json.tool
```

If the bronze layer is ingesting events but the silver layer is rejecting
them, a schema mismatch is likely.  Check rejected events:

```bash
curl -s "http://localhost:8000/api/v1/pipeline/silver/rejected?limit=5" | python3 -m json.tool
```

### 3.5 Migration Path if Schemas Have Drifted

If the Trebanx producer schema has evolved ahead of `trebanx-contracts`:

1. **Update `trebanx-contracts`** -- add the new fields to the JSON schemas
   and bump the version.
2. **Remount contracts** -- restart the Lakay container to pick up the new
   schema files:
   ```bash
   docker compose restart lakay
   ```
3. **Register new schema version** -- Lakay auto-registers schemas on first
   encounter, but you can also register explicitly through the bronze layer
   code.
4. **Backfill if needed** -- if old events lack new required fields, add a
   silver-layer transformation that supplies defaults.

If Lakay's expected schema is ahead of the Trebanx producer:

1. Coordinate with the Trebanx team to add the missing fields.
2. In the interim, configure the silver layer to tolerate missing optional
   fields (this is the default behavior -- required fields are enforced,
   optional fields fall back to nulls).

> **Checkpoint**: Confirm that sample events from all four Trebanx topics
> pass schema validation before proceeding.

---

## 4. Phase C -- Kafka Connection (Est. 1 hour)

### 4.1 Consumer Configuration

Lakay starts four Kafka consumers at application boot (see `src/main.py`
lifespan handler).  Each consumer subscribes to a single topic:

| Consumer Class | Source File | Topic | Consumer Group |
|----------------|------------|-------|----------------|
| `CircleConsumer` | `src/consumers/circle_consumer.py` | `trebanx.circle.events` | `lakay-intelligence` |
| `TransactionConsumer` | `src/consumers/transaction_consumer.py` | `trebanx.transaction.events` | `lakay-intelligence` |
| `SessionConsumer` | `src/consumers/session_consumer.py` | `trebanx.user.events` | `lakay-intelligence` |
| `RemittanceConsumer` | `src/consumers/remittance_consumer.py` | `trebanx.remittance.events` | `lakay-intelligence` |

All consumers use `aiokafka.AIOKafkaConsumer` with:
- `group_id` = `KAFKA_CONSUMER_GROUP` (default: `lakay-intelligence`)
- `auto_offset_reset` = `earliest`
- `enable_auto_commit` = `True`
- JSON deserialization via `json.loads()`

### 4.2 Topic Mapping Table

| Inbound (Consumed) | Purpose | Outbound (Produced) |
|---------------------|---------|---------------------|
| `trebanx.circle.events` | Circle lifecycle, contributions, payouts | `lakay.circles.tier-changes` |
| `trebanx.transaction.events` | Transaction scoring, fraud detection | `lakay.fraud.alerts` |
| `trebanx.user.events` | Behavioral profiles, ATO detection | `lakay.behavior.ato-alerts` |
| `trebanx.remittance.events` | Corridor analytics, compliance rules | `lakay.compliance.alerts`, `lakay.compliance.edd-triggers` |

### 4.3 Create Required Topics

If `KAFKA_AUTO_CREATE_TOPICS_ENABLE` is `false` on the Kafka cluster (common
in production), create topics manually:

```bash
# Inbound topics (if not already created by Trebanx)
kafka-topics --create --bootstrap-server <kafka-host>:9092 \
  --partitions 3 --replication-factor 3 \
  --topic trebanx.circle.events

kafka-topics --create --bootstrap-server <kafka-host>:9092 \
  --partitions 3 --replication-factor 3 \
  --topic trebanx.transaction.events

kafka-topics --create --bootstrap-server <kafka-host>:9092 \
  --partitions 3 --replication-factor 3 \
  --topic trebanx.user.events

kafka-topics --create --bootstrap-server <kafka-host>:9092 \
  --partitions 3 --replication-factor 3 \
  --topic trebanx.remittance.events

# Outbound topics (Lakay-owned)
kafka-topics --create --bootstrap-server <kafka-host>:9092 \
  --partitions 3 --replication-factor 3 \
  --topic lakay.fraud.alerts

kafka-topics --create --bootstrap-server <kafka-host>:9092 \
  --partitions 3 --replication-factor 3 \
  --topic lakay.circles.tier-changes

kafka-topics --create --bootstrap-server <kafka-host>:9092 \
  --partitions 3 --replication-factor 3 \
  --topic lakay.behavior.ato-alerts

kafka-topics --create --bootstrap-server <kafka-host>:9092 \
  --partitions 3 --replication-factor 3 \
  --topic lakay.compliance.alerts

kafka-topics --create --bootstrap-server <kafka-host>:9092 \
  --partitions 3 --replication-factor 3 \
  --topic lakay.compliance.edd-triggers
```

### 4.4 Consumer Group Verification

After Lakay has been running for at least 60 seconds with events flowing:

```bash
kafka-consumer-groups --bootstrap-server <kafka-host>:9092 \
  --group lakay-intelligence --describe
```

Confirm:
- All four topics appear
- `CURRENT-OFFSET` is advancing
- `LAG` is decreasing (or zero in steady state)

### 4.5 Verify Bronze Layer Ingestion

```bash
curl -s http://localhost:8000/api/v1/pipeline/bronze/stats | python3 -m json.tool
```

Expected output includes:

```json
{
    "total_events_ingested": 142,
    "events_by_type": {
        "transaction-initiated": 45,
        "circle-contribution-received": 30,
        "session-started": 52,
        "remittance-initiated": 15
    },
    "partitions_created": 4,
    "total_size_bytes": 28672,
    "buffered_events": {},
    "latest_checkpoints": {
        "trebanx.transaction.events": {"0": 44, "1": 23, "2": 18}
    }
}
```

> **Checkpoint**: `total_events_ingested` should be non-zero and
> `events_by_type` should show entries for all four inbound event types.

---

## 5. Phase D -- Data Validation (Est. 2-4 hours)

### 5.1 Run First Real Events

Allow the system to process real Trebanx events for at least 30 minutes.
During this period, monitor the logs for validation errors:

```bash
docker compose logs -f lakay 2>&1 | grep -E "(schema_validation|rejected|error|warning)"
```

### 5.2 Verification Checklist

#### Schema Validation

- [ ] Bronze stats show events ingested for all four topics
- [ ] Silver quality endpoint returns passing results:

```bash
curl -s http://localhost:8000/api/v1/pipeline/silver/quality | python3 -m json.tool
```

Check that `passed` counts are non-zero and `rejected` counts are
acceptably low (ideally zero, but a small percentage is normal during
initial alignment).

#### Feature Computation

- [ ] Fraud scoring produces results for `transaction-initiated` events:

```bash
# Check application logs for scoring output
docker compose logs lakay 2>&1 | grep "transaction_scored_via_consumer"
```

Each scored transaction log line includes: `score`, `composite_score`,
`risk_tier`, and `recommendation`.

- [ ] Behavioral profiles begin building for users with session events:

```bash
docker compose logs lakay 2>&1 | grep "user_event_received"
```

- [ ] Circle health scores compute when circle events arrive:

```bash
docker compose logs lakay 2>&1 | grep "circle_event_received"
```

#### Score Production

- [ ] Fraud alerts appear on the outbound topic:

```bash
kafka-console-consumer \
  --bootstrap-server <kafka-host>:9092 \
  --topic lakay.fraud.alerts \
  --max-messages 5 | python3 -m json.tool
```

- [ ] Compliance alerts (if thresholds crossed):

```bash
kafka-console-consumer \
  --bootstrap-server <kafka-host>:9092 \
  --topic lakay.compliance.alerts \
  --max-messages 5 | python3 -m json.tool
```

### 5.3 Troubleshooting Common Validation Issues

#### Schema Mismatches

**Symptom**: High `rejected` count in silver quality, log messages like
`schema_validation_error`.

**Fix**:
1. Pull rejected event samples:
   ```bash
   curl -s "http://localhost:8000/api/v1/pipeline/silver/rejected?limit=5" | python3 -m json.tool
   ```
2. Read the `rejection_reasons` array -- it will specify which fields
   failed validation.
3. Update either the Trebanx producer or the `trebanx-contracts` schema
   to reconcile.

#### Missing Fields

**Symptom**: `KeyError` in logs, scoring returns null or default values.

**Fix**: Verify the `payload` object in each event contains all fields
expected by the consumer handlers.  The transaction consumer expects:
`transaction_id`, `user_id`, `amount`, `currency`, `ip_address`,
`device_id`, `geo_location`, `type`, `initiated_at`, `recipient_id`.

#### Timezone Differences

**Symptom**: Velocity windows miscalculate (events appear outside their
expected window), impossible travel scores are wrong.

**Fix**: Confirm all `timestamp` and `initiated_at` fields use UTC.
Lakay assumes ISO 8601 UTC timestamps throughout.  If Trebanx sends local
times without offset, add a normalization step or fix at the producer.

#### Unexpected `event_type` Values

**Symptom**: Log messages like `no_handler_for_event`.

**Fix**: The Lakay consumer will log but skip events with unrecognized
`event_type` values.  Verify the producer uses the exact event type strings
listed in Section 3.3.

> **Checkpoint**: After 30+ minutes of real event flow, confirm zero or
> near-zero rejected events and at least one scored transaction in the logs.

---

## 6. Phase E -- Threshold Calibration (Est. 1-2 weeks)

### 6.1 Shadow Mode

Lakay should run in **shadow mode** for its first 1-2 weeks in production.
In shadow mode the system:

- Ingests all events and computes all scores
- Writes alerts to Kafka outbound topics
- **Does not** trigger any automated blocking or enforcement actions in Trebanx

To enable shadow mode, ensure the Trebanx platform is configured to:
1. Read from `lakay.fraud.alerts` but only log (do not block transactions)
2. Read from `lakay.compliance.alerts` but only log (do not file reports)
3. Read from `lakay.behavior.ato-alerts` but only log (do not lock accounts)

### 6.2 Review Score Distributions

After at least 3 days of event flow, examine score distributions via the
dashboard endpoints:

```bash
# Fraud score overview
curl -s http://localhost:8000/api/v1/dashboards/fraud | python3 -m json.tool

# Compliance overview
curl -s http://localhost:8000/api/v1/dashboards/compliance | python3 -m json.tool

# Circle health overview
curl -s http://localhost:8000/api/v1/dashboards/circles | python3 -m json.tool

# Platform health (all domains)
curl -s http://localhost:8000/api/v1/dashboards/platform | python3 -m json.tool

# Haiti corridor analytics
curl -s http://localhost:8000/api/v1/dashboards/corridor | python3 -m json.tool
```

Analyze the distributions:
- **Too many alerts?** -- Thresholds are too aggressive; raise them.
- **Zero alerts?** -- Thresholds may be too loose, or event volume is too low.
- **Alerts cluster at specific scores?** -- The scoring function may need
  weight adjustments.

### 6.3 Threshold Adjustment Procedure

#### Fraud Thresholds

Adjust via environment variables (no restart needed if using hot-reload,
otherwise restart the container):

```bash
# Raise the high-alert threshold from 0.6 to 0.7
export FRAUD_HIGH_THRESHOLD=0.7
export FRAUD_CRITICAL_THRESHOLD=0.85

# Adjust velocity limits
export FRAUD_TXN_COUNT_1H_MAX=15
export FRAUD_TXN_AMOUNT_24H_MAX=15000.0
```

Config source: `src/domains/fraud/config.py`

Key fraud thresholds:
- `FRAUD_HIGH_THRESHOLD` (default: `0.6`) -- score at or above this triggers a HIGH alert
- `FRAUD_CRITICAL_THRESHOLD` (default: `0.8`) -- score at or above this triggers a CRITICAL alert
- `FRAUD_LARGE_TXN_MIN` (default: `3000.0`) -- minimum amount for "large transaction" classification
- `FRAUD_CTR_SINGLE_THRESHOLD` (default: `8000.0`) -- single-transaction CTR trigger
- `FRAUD_CTR_DAILY_THRESHOLD` (default: `9000.0`) -- daily aggregate CTR trigger

#### Circle Health Thresholds

```bash
# Rebalance dimension weights (must sum to 1.0)
export CIRCLE_CONTRIBUTION_WEIGHT=0.30
export CIRCLE_MEMBERSHIP_WEIGHT=0.25
export CIRCLE_FINANCIAL_WEIGHT=0.30
export CIRCLE_TRUST_WEIGHT=0.15
```

Config source: `src/domains/circles/config.py`

#### Compliance Thresholds

```bash
# Adjust CTR threshold (federal requirement is $10,000 -- do not lower below this)
export COMPLIANCE_CTR_THRESHOLD=10000.0

# Tune structuring detection sensitivity
export COMPLIANCE_SAR_CONFIDENCE=0.65
export COMPLIANCE_STRUCTURING_LOOKBACK_DAYS=45

# Tune unusual-volume multiplier
export COMPLIANCE_VOLUME_MULTIPLIER=4.0
```

Config source: `src/domains/compliance/config.py`

> **Warning**: CTR thresholds are governed by 31 CFR Section 1010.311.
> The federal filing threshold is $10,000 and must not be raised above this
> value.  Pre-threshold warnings can be adjusted.

#### Behavior / ATO Thresholds

```bash
export BEHAVIOR_EMA_DECAY_RATE=0.20
export BEHAVIOR_STALENESS_DAYS=21
export BEHAVIOR_ATO_DEDUP_WINDOW=43200  # 12 hours instead of 24
```

Config source: `src/domains/behavior/config.py`

### 6.4 Serving Layer Threshold Adjustment

The ML model serving layer has its own score thresholds and hybrid scoring
configuration.  These are defined in `src/serving/config.py`:

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `ScoringThresholds.low_max` | `0.3` | Score ceiling for "low risk" |
| `ScoringThresholds.medium_max` | `0.6` | Score ceiling for "medium risk" |
| `ScoringThresholds.high_max` | `0.8` | Score ceiling for "high risk"; above = critical |
| `HybridScoringConfig.strategy` | `weighted_average` | How rule-based and ML scores combine |
| `HybridScoringConfig.rule_weight` | `0.6` | Weight for rule-based score |
| `HybridScoringConfig.ml_weight` | `0.4` | Weight for ML model score |
| `HybridScoringConfig.ml_enabled` | `true` | Whether the ML model participates in scoring |

To adjust the hybrid balance during calibration:
- Start with `ml_enabled=false` (rules only) to establish a baseline
- Enable ML and set `ml_weight=0.2` to blend conservatively
- Gradually increase `ml_weight` as model accuracy is validated

### 6.5 Apply Changes

After modifying environment variables:

```bash
# Restart to pick up new env vars
docker compose restart lakay

# Verify the service is healthy after restart
curl -s http://localhost:8000/health | python3 -m json.tool
curl -s http://localhost:8000/ready | python3 -m json.tool
```

> **Checkpoint**: At the end of the shadow period, alert volume should match
> the operations team's capacity.  Target: fewer than 50 HIGH/CRITICAL fraud
> alerts per day for a platform processing 1,000 transactions/day.

---

## 7. Phase F -- Model Retraining (Est. 1-2 days per cycle)

### 7.1 Prerequisites for Retraining

- **Minimum 30 days of real production data** in the bronze/silver/gold
  layers before the first retrain is meaningful.
- Gold datasets available:
  ```bash
  curl -s http://localhost:8000/api/v1/pipeline/gold/datasets | python3 -m json.tool
  ```

### 7.2 Retraining Procedure

1. **Extract training data from gold layer:**

   ```bash
   curl -s "http://localhost:8000/api/v1/pipeline/gold/fraud_training?limit=1000" | python3 -m json.tool
   ```

   The gold layer aggregates features (velocity, amount z-scores, behavioral
   signals) with labeled outcomes (confirmed fraud, false positives) into
   training-ready datasets.

2. **Trigger gold layer refresh (if stale):**

   ```bash
   curl -X POST http://localhost:8000/api/v1/pipeline/gold/fraud_training/refresh
   ```

3. **Train via MLflow experiment:**

   Create a new experiment using the Lakay experimentation framework:

   ```bash
   curl -X POST http://localhost:8000/api/v1/experiments \
     -H "Content-Type: application/json" \
     -d '{
       "name": "fraud-retrain-cycle-1",
       "description": "First retrain on 30 days of production data",
       "model_type": "fraud",
       "config": {}
     }'
   ```

   Start the experiment:

   ```bash
   curl -X PUT http://localhost:8000/api/v1/experiments/<experiment_id>/start
   ```

4. **Validate the candidate model:**

   ```bash
   curl -s http://localhost:8000/api/v1/experiments/<experiment_id>/results | python3 -m json.tool
   ```

   Check guardrails (the experiment framework enforces safety bounds):

   ```bash
   curl -s http://localhost:8000/api/v1/experiments/<experiment_id>/guardrails | python3 -m json.tool
   ```

   If `any_breached` is `true`, do not promote the model.

5. **A/B deploy the candidate:**

   Use the serving routing API to split traffic between the current
   champion and the new challenger:

   ```bash
   # Start with 90/10 split: 90% champion, 10% challenger
   curl -X POST http://localhost:8000/api/v1/serving/routing \
     -H "Content-Type: application/json" \
     -d '{"champion_pct": 90, "challenger_pct": 10}'
   ```

   Monitor the A/B test via:

   ```bash
   curl -s http://localhost:8000/api/v1/serving/routing | python3 -m json.tool
   curl -s http://localhost:8000/api/v1/serving/monitoring | python3 -m json.tool
   ```

6. **Promote or rollback:**

   If the challenger outperforms after 3-7 days:

   ```bash
   # Promote: 100% challenger
   curl -X POST http://localhost:8000/api/v1/serving/routing \
     -H "Content-Type: application/json" \
     -d '{"champion_pct": 0, "challenger_pct": 100}'

   # Then hot-reload to make challenger the new champion
   curl -X POST http://localhost:8000/api/v1/serving/reload
   ```

   If the challenger underperforms:

   ```bash
   # Rollback: 100% champion
   curl -X POST http://localhost:8000/api/v1/serving/routing \
     -H "Content-Type: application/json" \
     -d '{"champion_pct": 100, "challenger_pct": 0}'
   ```

### 7.3 Retraining Schedule Recommendation

| Cycle | When | Trigger |
|-------|------|---------|
| First retrain | 30 days after go-live | Calendar |
| Monthly retrain | Every 30 days | Calendar or drift detection alert |
| Emergency retrain | Anytime | Model drift score exceeds threshold (via `/api/v1/serving/monitoring`) |
| Post-incident retrain | After confirmed fraud incident | Manual trigger by ML engineer |

Monitor model drift continuously:

```bash
curl -s http://localhost:8000/api/v1/serving/monitoring | python3 -m json.tool
```

The `drift` section of the response indicates whether score distributions
have shifted significantly from the training distribution.

---

## 8. Phase G -- Go-Live

### 8.1 Switch from Shadow to Active Mode

When shadow mode calibration is complete and thresholds are validated:

1. **Notify the operations team** -- provide the finalized threshold values
   and expected alert volumes.
2. **Configure Trebanx to act on Lakay alerts:**
   - `lakay.fraud.alerts` -- enable transaction blocking for CRITICAL alerts
   - `lakay.behavior.ato-alerts` -- enable account lockout for CRITICAL ATO
     risk
   - `lakay.compliance.alerts` -- enable compliance workflow triggers
   - `lakay.compliance.edd-triggers` -- enable enhanced due diligence workflow
   - `lakay.circles.tier-changes` -- enable circle tier badge updates in UI
3. **Set `DEBUG=false`** in the `.env` file (disables CORS wildcard and
   verbose logging).
4. **Restart Lakay:**
   ```bash
   docker compose restart lakay
   ```

### 8.2 First 24 Hours Monitoring Checklist

- [ ] `/health` returns `"healthy"` -- check every 15 minutes (automate via monitoring)
- [ ] `/ready` returns HTTP 200 -- check every 5 minutes
- [ ] Kafka consumer lag is below 100 for all four topics
- [ ] Bronze ingestion stats are advancing (new events every minute)
- [ ] Fraud alert rate is within the expected range from shadow mode
- [ ] No `CRITICAL`-level log messages in `docker compose logs lakay`
- [ ] PostgreSQL connection pool is not exhausted (check for `pool_timeout` errors)
- [ ] Redis is responding (check for `ConnectionRefusedError` in logs)
- [ ] MinIO / S3 writes are succeeding (check for `bronze_flush_error` in logs)
- [ ] Memory usage is stable (no unbounded growth)
- [ ] Response time for `/health` is under 100ms

### 8.3 First Week Checklist

- [ ] Cumulative false positive rate reviewed with operations team
- [ ] Threshold adjustments applied if alert volume is too high / too low
- [ ] Silver layer rejection rate is below 1%
- [ ] Gold datasets are refreshing on schedule
- [ ] Compliance dashboard reviewed by compliance officer:
  ```bash
  curl -s http://localhost:8000/api/v1/dashboards/compliance | python3 -m json.tool
  ```
- [ ] No memory leaks (container RSS stable over 7 days)
- [ ] Disk usage growth rate is sustainable (extrapolate to 30/90/365 days)

### 8.4 First Month Checklist

- [ ] Model performance metrics reviewed (precision, recall, F1 from experiment results)
- [ ] First compliance summary report generated:
  ```bash
  curl -X POST http://localhost:8000/api/v1/pipeline/compliance-reports/summary \
    -H "Content-Type: application/json" \
    -d '{"period": "monthly"}'
  ```
- [ ] CTR report generated for the first month:
  ```bash
  curl -X POST http://localhost:8000/api/v1/pipeline/compliance-reports/ctr \
    -H "Content-Type: application/json" \
    -d '{"start_date": "2026-02-01", "end_date": "2026-02-28"}'
  ```
- [ ] Behavioral profile coverage > 60% of active users (profiles in "active" state)
- [ ] Circle health scores computed for all active circles
- [ ] Model retrain cycle scheduled (see Phase F)
- [ ] Audit trail reviewed:
  ```bash
  curl -X POST http://localhost:8000/api/v1/pipeline/compliance-reports/audit \
    -H "Content-Type: application/json" \
    -d '{"start_date": "2026-02-01", "end_date": "2026-02-28"}'
  ```

### 8.5 Rollback Procedure

If Lakay must be taken offline or reverted during go-live:

**Immediate mitigation (< 5 minutes):**

```bash
# Stop the Lakay container (Trebanx stops receiving alerts)
docker compose stop lakay
```

Trebanx should be configured to fail-open: if no alerts arrive on Lakay's
outbound topics, transactions proceed without ML scoring (rule-based limits
in Trebanx's own middleware still apply).

**Partial rollback (revert thresholds):**

```bash
# Restore previous .env and restart
cp .env.backup .env
docker compose restart lakay
```

**Full rollback (revert to previous container version):**

```bash
# Tag current image before deploying a new version
docker tag lakay-intelligence:latest lakay-intelligence:rollback-$(date +%Y%m%d)

# Pull or build previous version
docker compose build lakay  # from the previous git commit

# Restart
docker compose up -d lakay
```

**Database rollback:**

```bash
# Downgrade one Alembic revision
docker compose exec lakay alembic downgrade -1

# Or downgrade to a specific revision
docker compose exec lakay alembic downgrade <revision_id>
```

> **Important**: Always keep a `.env.backup` copy before any threshold
> changes.  Always tag Docker images before deploying new versions.

---

## 9. Troubleshooting Guide

### 9.1 Kafka Connection Failures

**Symptom**: Log message `kafka_consumers_failed_to_start` at boot, or
consumers silently stop processing.

**Diagnosis:**
```bash
# Check Kafka broker reachability from inside the container
docker compose exec lakay python3 -c "
import socket
try:
    s = socket.create_connection(('kafka', 29092), timeout=5)
    print('Kafka reachable')
    s.close()
except Exception as e:
    print(f'Kafka unreachable: {e}')
"
```

**Common causes and fixes:**
- **Wrong bootstrap servers** -- verify `KAFKA_BOOTSTRAP_SERVERS` matches the
  broker list.  Inside Docker Compose use `kafka:29092`; from outside use
  `localhost:9092`.
- **Network isolation** -- ensure the Lakay container and Kafka are on the
  same Docker network.
- **Broker not ready** -- Kafka may still be initializing.  Lakay logs a
  warning and starts without consumers; restart the container once Kafka
  is healthy.
- **SASL/SSL misconfiguration** -- if the production Kafka cluster requires
  authentication, additional aiokafka parameters must be added to the
  `BaseConsumer` constructor.

### 9.2 Feature Store Staleness

**Symptom**: Fraud scores are unexpectedly low/high because velocity or
behavioral features are stale.

**Diagnosis:**
```bash
# Check Redis for feature freshness
docker compose exec redis redis-cli INFO keyspace
docker compose exec redis redis-cli DBSIZE
```

**Fixes:**
- **Redis eviction** -- if `maxmemory` is set and `maxmemory-policy` is
  `allkeys-lru`, features may be evicted.  Increase Redis memory or use
  `volatile-lru`.
- **Consumer lag** -- if Kafka consumers are behind, features are computed
  from stale data.  Check consumer group lag (Section 4.4).
- **Profile staleness** -- behavioral profiles older than
  `BEHAVIOR_STALENESS_DAYS` (default: 30) are treated with wider tolerance
  bands.  This is by design; ensure session events are flowing to keep
  profiles fresh.

### 9.3 Model Loading Failures

**Symptom**: `/api/v1/serving/monitoring` shows `"loaded": false` and a
non-null `load_error`.

**Diagnosis:**
```bash
curl -s http://localhost:8000/api/v1/serving/monitoring | python3 -m json.tool
```

**Common causes:**
- **MLflow unreachable** -- verify `MLFLOW_TRACKING_URI` and that the MLflow
  server is running.
- **No model in registry** -- the model `fraud-detector-v0.1` must be
  registered in MLflow with a "Production" or "Staging" stage.
- **S3 artifact download failure** -- verify `MLFLOW_S3_ENDPOINT_URL` and
  credentials.

**Fix:**
```bash
# Force a model reload
curl -X POST http://localhost:8000/api/v1/serving/reload | python3 -m json.tool
```

If the model has never been trained, Lakay falls back to rule-based scoring
only (hybrid scoring with `ml_enabled=false` equivalent behavior).

### 9.4 PostgreSQL Connection Pool Exhaustion

**Symptom**: HTTP 500 errors, log messages containing `pool_timeout` or
`QueuePool limit`.

**Diagnosis:**
```bash
# Check active connections
docker compose exec postgres psql -U lakay -c "SELECT count(*) FROM pg_stat_activity WHERE datname='lakay';"
```

**Fixes:**
- **Increase pool size** -- modify the SQLAlchemy engine configuration in
  `src/db/database.py` (set `pool_size` and `max_overflow`).
- **Connection leak** -- look for database sessions that are not being
  closed.  Lakay uses `async_session_factory()` as a context manager; ensure
  all paths exit the context.
- **Too many consumers** -- each Kafka consumer uses its own session per
  event.  If event volume is extremely high, consider batching.

### 9.5 MinIO / S3 Access Errors

**Symptom**: `bronze_flush_error` in logs, data lake layers are empty.

**Diagnosis:**
```bash
# Check MinIO health (if using local MinIO)
curl -s http://localhost:9000/minio/health/live

# Check bucket exists
docker compose exec minio mc ls lakay/lakay-data-lake/ 2>/dev/null && echo "Bucket exists" || echo "Bucket missing"
```

**Common causes:**
- **Wrong endpoint** -- `DATALAKE_ENDPOINT` must include the protocol
  (`http://` or `https://`).
- **Credentials mismatch** -- verify `DATALAKE_ACCESS_KEY` and
  `DATALAKE_SECRET_KEY`.
- **Bucket does not exist** -- the `minio-setup` service creates buckets
  automatically in the Docker Compose stack; for external S3, create buckets
  manually.
- **IAM permissions** -- for AWS S3, the IAM role needs `s3:PutObject`,
  `s3:GetObject`, `s3:ListBucket` on the configured bucket.

### 9.6 How to Read Structured Logs

Lakay uses `structlog` for JSON-structured logging.  Each log line is a
JSON object.

```bash
# Stream logs with jq for readability
docker compose logs -f lakay 2>&1 | while read line; do echo "$line" | python3 -m json.tool 2>/dev/null || echo "$line"; done

# Filter for errors only
docker compose logs lakay 2>&1 | grep '"level":"error"'

# Filter for a specific event type
docker compose logs lakay 2>&1 | grep '"event":"transaction_scored_via_consumer"'

# Filter for a specific user
docker compose logs lakay 2>&1 | grep '"user_id":"<user-uuid>"'
```

Key log event names to watch:

| Log Event | Meaning |
|-----------|---------|
| `lakay_starting` | Application boot initiated |
| `kafka_consumers_started` | All Kafka consumers connected |
| `kafka_consumers_failed_to_start` | Consumer startup failed (Kafka unreachable) |
| `consumer_started` | Individual consumer connected to topic |
| `transaction_scored_via_consumer` | A transaction was scored (includes score, risk_tier) |
| `login_velocity_alert` | Login velocity threshold exceeded |
| `circle_event_received` | Circle event processed |
| `bronze_flush` | Bronze layer batch written to data lake |
| `bronze_flush_error` | Bronze write failed |
| `no_handler_for_event` | Event with unrecognized `event_type` received |
| `duplicate_event_skipped` | Idempotent duplicate detection |
| `message_processing_error` | Unhandled exception in event processing |

### 9.7 How to Use Dashboard Endpoints

All dashboards are accessible via `GET /api/v1/dashboards/*`.  They accept
optional `start_date` and `end_date` query parameters (ISO 8601 format).

```bash
# Platform-wide health overview
curl -s "http://localhost:8000/api/v1/dashboards/platform?start_date=2026-02-20&end_date=2026-02-27" | python3 -m json.tool

# Fraud domain
curl -s "http://localhost:8000/api/v1/dashboards/fraud?start_date=2026-02-20&end_date=2026-02-27" | python3 -m json.tool

# Circles domain
curl -s http://localhost:8000/api/v1/dashboards/circles | python3 -m json.tool

# Compliance domain
curl -s "http://localhost:8000/api/v1/dashboards/compliance?start_date=2026-02-20&end_date=2026-02-27" | python3 -m json.tool

# Haiti corridor analytics
curl -s "http://localhost:8000/api/v1/dashboards/corridor?start_date=2026-02-20&end_date=2026-02-27" | python3 -m json.tool
```

Additional pipeline diagnostic endpoints:

```bash
# Bronze ingestion stats
curl -s http://localhost:8000/api/v1/pipeline/bronze/stats | python3 -m json.tool

# Bronze partitions
curl -s "http://localhost:8000/api/v1/pipeline/bronze/partitions?event_type=transaction-initiated" | python3 -m json.tool

# Silver processing stats
curl -s http://localhost:8000/api/v1/pipeline/silver/stats | python3 -m json.tool

# Silver data quality
curl -s http://localhost:8000/api/v1/pipeline/silver/quality | python3 -m json.tool

# Silver rejected events (for debugging)
curl -s "http://localhost:8000/api/v1/pipeline/silver/rejected?event_type=transaction-initiated&limit=10" | python3 -m json.tool

# Gold datasets
curl -s http://localhost:8000/api/v1/pipeline/gold/datasets | python3 -m json.tool

# Model serving health
curl -s http://localhost:8000/api/v1/serving/monitoring | python3 -m json.tool

# A/B routing status
curl -s http://localhost:8000/api/v1/serving/routing | python3 -m json.tool
```

---

## 10. Operational Procedures

### 10.1 Daily Operations

**Estimated time: 15-30 minutes**

| Task | Command / Action | What to Look For |
|------|------------------|------------------|
| Check service health | `curl -s http://localhost:8000/health` | `"status": "healthy"`, uptime advancing |
| Check readiness | `curl -s http://localhost:8000/ready` | HTTP 200, all dependencies `true` |
| Review Kafka consumer lag | `kafka-consumer-groups --group lakay-intelligence --describe` | Lag < 100 for all partitions |
| Review fraud alerts | `curl -s http://localhost:8000/api/v1/dashboards/fraud` | Alert count within expected range |
| Review compliance alerts | `curl -s http://localhost:8000/api/v1/dashboards/compliance` | No unexpected spikes |
| Check bronze ingestion | `curl -s http://localhost:8000/api/v1/pipeline/bronze/stats` | `total_events_ingested` advancing |
| Check silver quality | `curl -s http://localhost:8000/api/v1/pipeline/silver/quality` | Rejection rate < 1% |
| Scan logs for errors | `docker compose logs --since 24h lakay 2>&1 \| grep '"level":"error"'` | Ideally zero error-level messages |
| Check container resource usage | `docker stats lakay --no-stream` | CPU < 80%, Memory < 80% of limit |

### 10.2 Weekly Operations

**Estimated time: 1-2 hours**

| Task | Command / Action | What to Look For |
|------|------------------|------------------|
| Compliance weekly summary | `curl -X POST .../compliance-reports/summary -d '{"period":"weekly"}'` | Summary generated without errors |
| Model drift check | `curl -s .../serving/monitoring` | Drift metrics within acceptable bounds |
| Experiment review | `curl -s .../experiments?status=running` | Active experiments progressing; guardrails not breached |
| Circle health review | `curl -s .../dashboards/circles` | No circles in "critical" health tier without investigation |
| Corridor analytics | `curl -s .../dashboards/corridor` | US-HT corridor volume within expected range |
| Gold dataset freshness | `curl -s .../pipeline/gold/datasets` | All datasets refreshed within the last 7 days |
| Review rejected events | `curl -s .../pipeline/silver/rejected?limit=20` | Investigate any new rejection patterns |
| Disk usage check | `docker system df` | Ensure disk is not filling up |

### 10.3 Monthly Operations

**Estimated time: 4-8 hours**

| Task | Description |
|------|-------------|
| **Compliance review** | Generate CTR and SAR reports for the month. Review with compliance officer. File reports as required by 31 CFR 1010.311 and 31 CFR 1022.320. |
| **Monthly compliance summary** | `curl -X POST .../compliance-reports/summary -d '{"period":"monthly"}'` |
| **Audit readiness report** | `curl -X POST .../compliance-reports/audit -d '{"start_date":"...", "end_date":"..."}'` |
| **Model performance review** | Compare model precision/recall against previous month. Check if retrain is needed. |
| **Threshold review** | Review fraud, compliance, and behavior thresholds against actual alert volumes and false positive rates. Adjust per Section 6.3. |
| **Customer risk scoring review** | Review risk score distributions. Ensure risk level thresholds (`low_max`, `medium_max`, `high_max`) produce sensible tier distributions. |
| **FATF list update** | Verify the `high_risk_countries` list in compliance config matches the latest FATF grey/black lists. |
| **Behavioral profile audit** | Check profile coverage (% of active users with "active" profiles) and staleness rates. |
| **Database maintenance** | Run `VACUUM ANALYZE` on PostgreSQL. Check table sizes and index health. |
| **Backup verification** | Verify PostgreSQL backups are completing and restorable. Verify MinIO/S3 data is replicated. |

### 10.4 Quarterly Operations

**Estimated time: 2-5 days**

| Task | Description |
|------|-------------|
| **Model retrain cycle** | Full retrain using latest 90 days of data. Follow the procedure in Section 7. |
| **Security scan** | Scan the Docker image for CVEs: `docker scout cves lakay-intelligence:latest`. Scan Python dependencies: `pip-audit`. |
| **Dependency updates** | Update Python dependencies in `pyproject.toml`. Rebuild and test. Pay special attention to `aiokafka`, `asyncpg`, `mlflow`, `pydantic`. |
| **trebanx-contracts sync** | Verify the local contracts still match the Trebanx producer schemas. Run the schema alignment procedure (Section 3). |
| **Capacity planning** | Review resource usage trends. Project growth for the next quarter. Resize infrastructure if needed. |
| **Compliance audit preparation** | Ensure all CTR/SAR reports are filed. Generate quarterly audit readiness report. Review audit trail completeness. |
| **PII key rotation** | Rotate `PII_TOKEN_SECRET` and `PII_ENCRYPTION_KEY`. This requires re-tokenizing any cached PII -- coordinate with the data engineering team. |
| **Disaster recovery drill** | Practice the rollback procedure (Section 8.5). Restore PostgreSQL from backup and verify data integrity. |

---

## Appendix A -- Quick Reference: All API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness probe |
| GET | `/ready` | Readiness probe (checks DB + Redis) |
| GET | `/api/v1/pipeline/bronze/stats` | Bronze ingestion statistics |
| GET | `/api/v1/pipeline/bronze/partitions` | List bronze partitions |
| GET | `/api/v1/pipeline/silver/stats` | Silver processing statistics |
| GET | `/api/v1/pipeline/silver/quality` | Silver data quality results |
| GET | `/api/v1/pipeline/silver/rejected` | Sample rejected events |
| GET | `/api/v1/pipeline/gold/datasets` | List gold datasets |
| GET | `/api/v1/pipeline/gold/{dataset_name}` | Query a gold dataset |
| POST | `/api/v1/pipeline/gold/{dataset_name}/refresh` | Refresh a gold dataset |
| GET | `/api/v1/dashboards/platform` | Platform health dashboard |
| GET | `/api/v1/dashboards/fraud` | Fraud overview dashboard |
| GET | `/api/v1/dashboards/circles` | Circle health dashboard |
| GET | `/api/v1/dashboards/compliance` | Compliance overview dashboard |
| GET | `/api/v1/dashboards/corridor` | Haiti corridor dashboard |
| POST | `/api/v1/serving/reload` | Hot-reload ML model from MLflow |
| GET | `/api/v1/serving/routing` | A/B routing configuration |
| POST | `/api/v1/serving/routing` | Update A/B traffic split |
| GET | `/api/v1/serving/monitoring` | Model health + drift metrics |
| POST | `/api/v1/experiments` | Create experiment |
| GET | `/api/v1/experiments` | List experiments |
| GET | `/api/v1/experiments/{id}` | Get experiment details |
| PUT | `/api/v1/experiments/{id}/start` | Start experiment |
| PUT | `/api/v1/experiments/{id}/pause` | Pause experiment |
| PUT | `/api/v1/experiments/{id}/complete` | Complete experiment |
| GET | `/api/v1/experiments/{id}/results` | Experiment statistical results |
| GET | `/api/v1/experiments/{id}/guardrails` | Experiment guardrail status |
| POST | `/api/v1/pipeline/compliance-reports/ctr` | Generate CTR report |
| POST | `/api/v1/pipeline/compliance-reports/sar` | Generate SAR report |
| POST | `/api/v1/pipeline/compliance-reports/summary` | Generate compliance summary |
| POST | `/api/v1/pipeline/compliance-reports/audit` | Generate audit report |
| GET | `/api/v1/pipeline/compliance-reports` | List generated reports |
| GET | `/api/v1/pipeline/compliance-reports/{id}` | Retrieve specific report |

## Appendix B -- Kafka Topic Reference

### Inbound (Consumed by Lakay)

| Topic | Event Types | Consumer | Partition Count (Recommended) |
|-------|-------------|----------|-------------------------------|
| `trebanx.circle.events` | `circle-created`, `circle-member-joined`, `circle-member-dropped`, `circle-contribution-received`, `circle-contribution-missed`, `circle-payout-executed`, `circle-completed`, `circle-failed` | `CircleConsumer` | 3 |
| `trebanx.transaction.events` | `transaction-initiated`, `transaction-completed`, `transaction-failed`, `transaction-flagged` | `TransactionConsumer` | 3 |
| `trebanx.user.events` | `user-registered`, `user-verified`, `user-profile-updated`, `login-attempt`, `login-success`, `login-failed`, `session-started`, `session-ended`, `device-registered`, `user-action-performed` | `SessionConsumer` | 3 |
| `trebanx.remittance.events` | `remittance-initiated`, `remittance-processing`, `remittance-completed`, `remittance-failed`, `exchange-rate-updated` | `RemittanceConsumer` | 3 |

### Outbound (Produced by Lakay)

| Topic | Source Domain | Purpose |
|-------|--------------|---------|
| `lakay.fraud.alerts` | Fraud | Real-time fraud score alerts (HIGH and CRITICAL) |
| `lakay.circles.tier-changes` | Circles | Circle health tier transitions |
| `lakay.behavior.ato-alerts` | Behavior | Account takeover risk alerts |
| `lakay.compliance.alerts` | Compliance | Regulatory compliance alerts (CTR, structuring, etc.) |
| `lakay.compliance.edd-triggers` | Compliance | Enhanced due diligence triggers |

## Appendix C -- Docker Compose Service Map

```
                    +-----------+
                    | zookeeper |
                    +-----+-----+
                          |
                    +-----+-----+
          +-------->+   kafka    +<--------+
          |         +-----+-----+         |
          |               |               |
    (consume)        (consume)       (produce)
          |               |               |
    +-----+-----+  +-----+-----+  +------+------+
    |  Trebanx  |  |  Trebanx  |  |    lakay    |
    | (external)|  | (external)|  | :8000 (API) |
    +-----------+  +-----------+  +--+---+---+--+
                                    |   |   |
                         +----------+   |   +----------+
                         |              |              |
                   +-----+-----+  +----+----+  +------+------+
                   |  postgres  |  |  redis  |  |    minio    |
                   |   :5432    |  |  :6379  |  | :9000/:9001 |
                   +-----+------+  +---------+  +------+------+
                         |                             |
                   +-----+------+               +------+------+
                   |   mlflow   |               | minio-setup |
                   |   :5000    |               | (init only) |
                   +------------+               +-------------+
```

## Appendix D -- Environment File Template (Production)

```bash
# === Lakay Intelligence Production Configuration ===
# Copy this template and fill in production values.

APP_NAME=lakay-intelligence
APP_VERSION=0.1.0
DEBUG=false
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8000

# PostgreSQL (use strong credentials)
DATABASE_URL=postgresql+asyncpg://lakay:<STRONG_PASSWORD>@<POSTGRES_HOST>:5432/lakay

# Kafka (comma-separated broker list)
KAFKA_BOOTSTRAP_SERVERS=<BROKER1>:9092,<BROKER2>:9092,<BROKER3>:9092
KAFKA_CONSUMER_GROUP=lakay-intelligence
KAFKA_AUTO_OFFSET_RESET=earliest

# Redis
REDIS_URL=redis://<REDIS_HOST>:6379/0

# Contracts (mounted volume in Docker)
CONTRACTS_PATH=/contracts

# Data Lake (MinIO or S3)
DATALAKE_ENDPOINT=https://<S3_ENDPOINT>
DATALAKE_ACCESS_KEY=<ACCESS_KEY>
DATALAKE_SECRET_KEY=<SECRET_KEY>
DATALAKE_BUCKET=lakay-data-lake

# PII Protection (generate strong random values)
PII_TOKEN_SECRET=<64_CHAR_HEX_STRING>
PII_ENCRYPTION_KEY=<32_BYTE_BASE64_STRING>

# MLflow
MLFLOW_TRACKING_URI=http://<MLFLOW_HOST>:5000
AWS_ACCESS_KEY_ID=<ACCESS_KEY>
AWS_SECRET_ACCESS_KEY=<SECRET_KEY>
MLFLOW_S3_ENDPOINT_URL=https://<S3_ENDPOINT>

# Fraud thresholds (adjust after shadow mode calibration)
# FRAUD_HIGH_THRESHOLD=0.6
# FRAUD_CRITICAL_THRESHOLD=0.8

# Compliance (do not raise CTR threshold above 10000.0)
# COMPLIANCE_CTR_THRESHOLD=10000.0
```
