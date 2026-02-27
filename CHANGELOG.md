# Changelog

All notable changes to Lakay Intelligence are documented in this file.

## [0.10.0] — Phase 10: Integration Preparation

The final phase. Prepares Lakay Intelligence for production integration with the Trebanx platform.

### Added
- **Comprehensive integration test suite** (`tests/integration/`)
  - API contract tests for all 60+ endpoints across 10 domain routers
  - Cross-domain integration tests validating fraud→compliance, ATO→fraud, circle→fraud, and multi-domain event flows
  - End-to-end flow tests covering 5 user lifecycle scenarios (onboarding, normal usage, fraud incident, circle failure, compliance escalation)
  - Schema compliance tests verifying all event and response schemas
  - Security audit tests covering OWASP API Security Top 10
- **Load test harness** (`tests/load/harness.py`)
  - Configurable throughput, stress, burst, and stability test profiles
  - Latency percentile tracking (p50, p95, p99) per endpoint
  - SLA compliance verification against performance targets
- **Integration runbook** (`docs/integration/runbook.md`)
  - 7-phase deployment guide (environment setup → go-live)
  - Environment variable reference for all configurable parameters
  - Troubleshooting guide with common issues and resolutions
  - Operational procedures (daily, weekly, monthly, quarterly)
- **API reference** (`docs/integration/api-reference.md`)
  - Complete documentation for every endpoint with request/response schemas
  - Organized by domain with examples and error codes
- **Architecture overview** (`docs/integration/architecture.md`)
  - System architecture diagram with data flows
  - Module dependency map
  - Technology stack with version numbers and design rationale
- **Model governance documentation** (`docs/governance/`)
  - Model inventory with training data, features, and performance metrics
  - Bias audit template for fairness evaluation across protected groups
  - Drift monitoring procedures with alert thresholds
  - Model deployment procedures with A/B testing and rollback
- **Generator documentation** (`docs/integration/generators.md`)
  - Complete guide for running and extending all 4 synthetic data generators
- **Configuration reference** (`docs/integration/configuration.md`)
  - Every configurable parameter across all modules with types, defaults, and descriptions
- **Security audit report** (`docs/integration/security-audit-report.md`)
  - OWASP category-by-category findings
  - Dependency scan results template
  - Secrets management and data security verification
- **Load test results template** (`docs/integration/load-test-results.md`)
  - SLA compliance tables and bottleneck analysis format
- **CHANGELOG.md** documenting all 10 phases

---

## [0.9.0] — Phase 9: Data Pipeline, Experiments, Dashboards & Compliance Reports

### Added
- **Three-tier data pipeline** (bronze/silver/gold) with PII tokenization
  - Bronze layer: raw event ingestion to Parquet with Kafka offset tracking
  - Silver layer: validation, deduplication, PII tokenization, quality logging
  - Gold layer: 6 materialized datasets (daily-transaction-summary, circle-lifecycle-summary, user-risk-dashboard, compliance-reporting, platform-health, haiti-corridor-analytics)
- **A/B experimentation framework** with guardrail metrics
  - Experiment lifecycle management (draft → running → paused → completed)
  - User-hash based deterministic variant assignment
  - Statistical significance testing and guardrail monitoring
- **5 operational dashboards** (platform health, fraud operations, circle health, compliance, Haiti corridor)
- **Compliance reporting pipeline** (CTR reports, SAR reports, compliance summaries, audit reports)
- API endpoints: `GET/POST /api/v1/pipeline/*`, `GET/POST/PUT /api/v1/experiments/*`, `GET /api/v1/dashboards/*`, `GET/POST /api/v1/pipeline/compliance-reports/*`

---

## [0.8.0] — Phase 8: Compliance Intelligence

### Added
- **BSA/AML transaction monitoring** with 6 monitoring rules
- **CTR auto-flagging** with filing package assembly for transactions ≥ $10,000
- **Structuring detection** with 4 typologies (micro, slow, fan-out, funnel)
- **SAR narrative draft generator** with machine-generated disclaimer
- **Dynamic customer risk scoring** with EDD triggers and review scheduling
- **Full audit trail** for compliance actions
- API endpoints: `GET/PUT /api/v1/compliance/alerts/*`, `GET/POST/PUT /api/v1/compliance/cases/*`, `GET/POST/PUT /api/v1/compliance/sar/*`, `GET/POST /api/v1/compliance/risk/*`, `GET /api/v1/compliance/ctr/*`

---

## [0.7.0] — Phase 7: Behavioral Analytics & ATO Detection

### Added
- **Per-user adaptive behavioral profiles** with 5 baseline dimensions (session, temporal, device, geographic, engagement)
- **Session anomaly scoring** with composite scoring across all dimensions
- **Account takeover (ATO) detection pipeline** with graduated responses (none → re-auth → step-up → lock)
- **Engagement scoring** with lifecycle stage classification (new → onboarding → active → power user → declining → dormant → churned → reactivated)
- **Cross-domain integration**: ATO alerts feed into fraud scoring and compliance monitoring
- API endpoints: `GET /api/v1/behavior/users/*/profile`, `POST /api/v1/behavior/sessions/score`, `GET /api/v1/behavior/users/*/engagement`, `POST /api/v1/behavior/ato/assess`, `GET/PUT /api/v1/behavior/ato/alerts/*`

---

## [0.6.0] — Phase 6: Circle Health Scoring

### Added
- **Multi-dimensional circle health scoring** (0–100) across 4 dimensions: contribution reliability, membership stability, financial progress, trust/integrity
- **Circle anomaly detection**: coordinated late payments, post-payout disengagement, free-rider behavior, behavioral shifts
- **Risk classification**: Healthy / At-Risk / Critical with actionable recommendations
- **Tier change detection** with Kafka event publishing
- API endpoints: `POST /api/v1/circles/{id}/score`, `GET /api/v1/circles/{id}/health`, `GET /api/v1/circles/health/summary`, `GET /api/v1/circles/{id}/anomalies`, `GET /api/v1/circles/{id}/classification`, `GET /api/v1/circles/at-risk`

---

## [0.5.0] — Phase 5: Feature Store Integration

### Added
- **Feast feature store** integration with PostgreSQL offline store and Redis online store
- Feature sets: fraud features, behavioral features, circle features
- Validated zero training-serving skew between offline and online stores
- Feature materialization pipeline
- API endpoints: `POST /api/v1/features/materialize`, `GET /api/v1/features/status`

---

## [0.4.0] — Phase 4: ML Model Serving

### Added
- **MLflow model registry** integration with MinIO artifact storage
- **In-process model serving** with pyfunc prediction
- **Hot-reload capability** for production model updates without downtime
- **A/B routing** with champion/challenger traffic split (deterministic user-hash based)
- **Graceful fallback** to rule-based scoring when ML model unavailable
- **Model monitoring**: prediction score distributions, latency tracking, drift detection
- **GBT fraud model** (`fraud-detector-v0.2`) trained on PaySim via Feast features
- API endpoints: `POST /api/v1/serving/reload`, `GET/POST /api/v1/serving/routing`, `GET /api/v1/serving/monitoring`

---

## [0.3.0] — Phase 3: Rule-Based Fraud Detection

### Added
- **Rule-based fraud detection engine** with 5 rule categories
  - Velocity checks: transaction count/amount thresholds (1h, 24h)
  - Amount rules: high-amount detection, structuring near $3K and $10K
  - Geographic rules: impossible travel detection, new geolocation flagging
  - Pattern rules: duplicate transactions, round-amount clustering, temporal structuring
  - Composite risk scoring with weighted category aggregation
- **Alert pipeline** with severity levels (high, critical) and Kafka publishing
- **Risk tier classification**: low / medium / high / critical with recommendations (allow / monitor / hold / block)
- API endpoints: `POST /api/v1/fraud/score`, `GET /api/v1/fraud/rules`, `GET /api/v1/fraud/alerts`

---

## [0.2.0] — Phase 2: Service Infrastructure

### Added
- **Dockerized FastAPI service** with PostgreSQL, Kafka, and Redis
- **Kafka consumers** for 4 event types (circle, transaction, session, remittance)
- **Structured logging** with structlog (JSON format)
- **Health and readiness endpoints** (`/health`, `/ready`)
- **CI/CD pipeline** with GitHub Actions (lint, test, build)
- **Database models** with SQLAlchemy async ORM and Alembic migrations
- **Error handling middleware** with structured error responses

---

## [0.1.0] — Phase 1: Event Schema Contracts & Synthetic Data Generators

### Added
- **Event schema contracts** (JSON Schema) in trebanx-contracts repository
  - circle-created, circle-member-joined, circle-contribution, circle-payout
  - transaction-initiated, transaction-completed, transaction-failed
  - session-started, session-ended, login-attempt
  - remittance-initiated, remittance-completed
- **4 synthetic data generators** producing schema-valid events
  - Circle generator: full sou-sou lifecycle simulation
  - Transaction generator: payment patterns with configurable fraud injection
  - Session generator: user session behavior with device/location patterns
  - Remittance generator: US→Haiti corridor with exchange rates
- **Generator CLI** with YAML configuration, seeded RNG, stdout/file output
- **Schema validation tests** confirming all generators produce valid events

---

## Deferred Items

The following items were identified during development and deferred to post-integration:

- **Real Feast integration**: Feature store interface is ready; connect to actual Feast deployment when Trebanx infrastructure is available
- **Kafka output from generators**: CLI supports stdout and file; Kafka output mode is stubbed
- **Real-time dashboard data**: Dashboard endpoints aggregate from database; real-time streaming aggregation deferred
- **Neural network models**: GBT chosen for interpretability; neural nets may be evaluated when data volume justifies complexity
- **Multi-region deployment**: Current architecture is single-region; horizontal scaling documented in load test results
