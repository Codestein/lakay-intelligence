# Lakay Intelligence Architecture Overview

> Phase 10 - Task 10.5 | Integration Documentation

## 1. System Overview

Lakay Intelligence is an AI/ML microservice for **Trebanx** — a fintech platform
serving the Haitian diaspora through digital sou-sou (rotating savings circles)
and remittances to Haiti. The microservice provides the following capabilities:

- **Fraud Detection** — Real-time transaction risk scoring with a weighted
  rules engine, feature computation, alert generation, and ML model scoring.
- **Circle Health Scoring** — Health assessment of sou-sou circles including
  payment timing, member participation, risk classification, and anomaly
  detection.
- **Behavioral Analytics** — User behavior profiling, session anomaly detection,
  account takeover (ATO) alerting, and engagement scoring.
- **Compliance Intelligence** — AML/CFT monitoring including Currency
  Transaction Reports (CTR), Suspicious Activity Reports (SAR), structuring
  detection, risk scoring, and Enhanced Due Diligence (EDD) triggers.
- **Data Pipeline** — Three-tier medallion architecture (bronze/silver/gold)
  for raw event ingestion, quality-checked transformations, and business-ready
  aggregated datasets.
- **Model Serving** — In-process ML model loading via MLflow, A/B routing
  between champion and challenger models, feature drift detection (PSI), and
  deployment lifecycle management.

Lakay Intelligence is designed to be **event-driven**: it consumes domain events
from Trebanx via Apache Kafka, processes them through domain-specific modules,
persists state to PostgreSQL, caches features in Redis, and writes analytical
data to a MinIO-backed data lake in Apache Parquet format. It also exposes a
REST API (FastAPI) for synchronous scoring, querying, and operational endpoints.

---

## 2. Architecture Diagram

```
                            TREBANX PLATFORM
                                  |
                                  v
                 +-------------------------------+
                 |        Apache Kafka            |
                 |  (Confluent Platform 7.5)      |
                 +---------+-----+-----+---------+
                           |     |     |
           Input Topics:   |     |     |
           trebanx.circle.events |     |
           trebanx.transaction.events  |
           trebanx.user.events         |
           trebanx.remittance.events
           trebanx.security.events
                           |     |     |
                           v     v     v
         +-------------------------------------------+
         |         LAKAY INTELLIGENCE SERVICE         |
         |          (FastAPI + uvicorn :8000)          |
         |                                            |
         |  +---------------------------------------+ |
         |  |          Kafka Consumers              | |
         |  |  CircleConsumer  TransactionConsumer   | |
         |  |  SessionConsumer RemittanceConsumer    | |
         |  +----------|--------|------|------------+ |
         |             |        |      |              |
         |             v        v      v              |
         |  +---------------------------------------+ |
         |  |          Domain Modules               | |
         |  |                                       | |
         |  |  +--------+  +---------+  +---------+ | |
         |  |  | Fraud   |  | Circles |  |Behavior | | |
         |  |  | Scorer  |  | Health  |  |Profiler | | |
         |  |  | Rules   |  | Scoring |  |Anomaly  | | |
         |  |  | Alerts  |  | Classif.|  |ATO Det. | | |
         |  |  | Features|  | Anomaly |  |Engagem. | | |
         |  |  +----+----+  +----+----+  +----+----+ | |
         |  |       |            |            |       | |
         |  |  +----+----+  +---+------------+---+   | |
         |  |  |Compliance|  |    Feature Store   |   | |
         |  |  | CTR/SAR  |  |  (Feast stub impl) |   | |
         |  |  |Structur. |  +--------------------+   | |
         |  |  |Risk Scor.|                           | |
         |  |  |EDD Trigg.|                           | |
         |  |  +----------+                           | |
         |  +---------------------------------------+ |
         |             |        |      |              |
         |  +----------|--------|------|------------+ |
         |  |       Serving Infrastructure          | |
         |  |  ModelServer   ModelRouter (A/B)      | |
         |  |  DriftDetector DeployManager          | |
         |  |  (MLflow registry integration)        | |
         |  +---------------------------------------+ |
         |             |        |      |              |
         |  +----------|--------|------|------------+ |
         |  |         Data Pipeline                 | |
         |  |  BronzeIngestionBuffer                | |
         |  |  SilverProcessor (quality + PII tok.) | |
         |  |  GoldProcessor (aggregations)         | |
         |  +---------------------------------------+ |
         |             |        |      |              |
         |  +----------|--------|------|------------+ |
         |  |          API Layer (FastAPI)           | |
         |  |  /health  /fraud  /circles  /behavior | |
         |  |  /compliance  /serving  /pipeline     | |
         |  |  /experiments /dashboards             | |
         |  |  /compliance-reports                  | |
         |  +---------------------------------------+ |
         +--------+----------+---------+---+----------+
                  |          |         |   |
                  v          v         v   v
         +----------+ +----------+ +----------+ +-----------+
         |PostgreSQL | |  Redis   | |  MinIO   | |  MLflow   |
         |   16      | | 7-alpine | | (S3-compat)| | v2.19+  |
         |           | |          | |          | |           |
         | raw_events| | features | | bronze/  | | model     |
         |fraud_score| | cache    | | silver/  | | registry  |
         | alerts    | | sessions | | gold/    | | artifacts |
         | circles   | |          | | rejected/| | tracking  |
         | compliance| |          | | (Parquet)| |           |
         | pii_tokens| |          | |          | |           |
         | pipeline  | |          | |          | |           |
         | metadata  | |          | |          | |           |
         +----------+ +----------+ +----------+ +-----------+
                  |
                  v
         +-------------------------------+
         |        Apache Kafka            |
         |       Output Topics:           |
         |  lakay.fraud.alerts            |
         |  lakay.circles.tier-changes    |
         |  lakay.behavior.ato-alerts     |
         |  lakay.compliance.alerts       |
         |  lakay.compliance.edd-triggers |
         +-------------------------------+
                  |
                  v
            TREBANX PLATFORM
         (consumes alerts/events)
```

### Data Pipeline Detail (Medallion Architecture)

```
  Kafka Topics ──> BronzeIngestionBuffer ──> MinIO: bronze/
  (raw events)     (flush every 60s or         (immutable, raw
                    1000 events to Parquet)      Parquet partitions)
                                                     |
                                                     v
                                              SilverProcessor
                                              - Quality checks
                                              - Deduplication
                                              - PII tokenization (HMAC)
                                              - Dead-letter for rejected
                                                     |
                                                     v
                                               MinIO: silver/
                                              (clean, PII-safe Parquet)
                                                     |
                                                     v
                                              GoldProcessor
                                              - daily-transaction-summary
                                              - circle-lifecycle-summary
                                              - user-risk-dashboard
                                              - compliance-reporting
                                              - platform-health
                                              - haiti-corridor-analytics
                                                     |
                                                     v
                                               MinIO: gold/
                                              (business-ready aggregations)
```

---

## 3. Module Dependency Map

The following table shows each major module and its infrastructure
dependencies. An arrow (`->`) indicates a runtime dependency.

| Module | Dependencies |
|--------|-------------|
| **Fraud** (`src/domains/fraud/`) | Feature Store (Redis) -> feature computation; PostgreSQL -> FraudScore, Alert persistence; Kafka -> alert publishing (`lakay.fraud.alerts`); Rules Engine (in-process); ML Model (optional, via Serving) |
| **Circles** (`src/domains/circles/`) | Feature Store (Redis) -> circle feature retrieval; PostgreSQL -> circle health state; Kafka -> tier change events (`lakay.circles.tier-changes`); Scoring, Classification, Anomaly modules (in-process) |
| **Behavior** (`src/domains/behavior/`) | Feature Store (Redis) -> behavioral feature retrieval; PostgreSQL -> behavior profile persistence; Anomaly detection, ATO detection, Engagement scoring (in-process) |
| **Compliance** (`src/domains/compliance/`) | PostgreSQL -> CTR/SAR records, compliance cases, risk scores; In-memory stores for active alert tracking; Kafka -> compliance alerts and EDD triggers |
| **Pipeline** (`src/pipeline/`) | MinIO -> bronze/silver/gold Parquet storage; PostgreSQL -> partition metadata, schema registry, ingestion checkpoints, quality logs, gold dataset metadata; PII Tokenizer (in-process, HMAC-based) |
| **Serving** (`src/serving/`) | MLflow -> model registry and artifact loading; Redis -> feature caching for inference; Drift Detector (in-process, PSI); Model Router (in-process, A/B routing) |
| **Feature Store** (`src/features/`) | Redis -> feature read/write (stub implementation, Feast interface ready) |
| **Consumers** (`src/consumers/`) | Kafka -> event consumption (aiokafka); PostgreSQL -> raw event persistence; Domain Modules -> event routing/handling |
| **API** (`src/api/`) | Domain Modules -> request handling; PostgreSQL -> session management; Middleware -> structured logging, error handling, CORS |

### Module Interaction Graph

```
  Consumers ──> Domain Modules ──> Feature Store ──> Redis
       |              |
       |              +──> PostgreSQL (state)
       |              |
       |              +──> Kafka (output alerts)
       |
       +──> Pipeline (bronze ingestion)

  API Routes ──> Domain Modules (same as above)
       |
       +──> Pipeline (query/refresh)
       |
       +──> Serving (model management, scoring)

  Serving ──> MLflow (model loading)
       |
       +──> Drift Detector (PSI monitoring)
       |
       +──> Model Router (champion/challenger A/B)
```

---

## 4. Data Flow

### 4.1 Event Processing Flow (Real-Time)

```
1. Trebanx Platform emits domain events
        |
        v
2. Kafka Topics (trebanx.circle.events, trebanx.transaction.events, etc.)
        |
        v
3. Lakay Kafka Consumers (CircleConsumer, TransactionConsumer, etc.)
   - Deserialize JSON from Kafka message
   - Route by event_type to registered handler
   - Persist raw event to PostgreSQL (idempotent via event_id)
        |
        v
4. Domain Module Processing
   - Fraud: compute features -> evaluate rules -> score -> persist -> alert
   - Circles: compute health -> classify tier -> detect anomalies -> persist
   - Behavior: update profile -> detect anomalies -> score engagement
   - Compliance: check thresholds -> generate CTR/SAR -> risk score
        |
        v
5. Outputs
   - PostgreSQL: scores, alerts, profiles, compliance records
   - Kafka: lakay.fraud.alerts, lakay.circles.tier-changes,
            lakay.behavior.ato-alerts, lakay.compliance.alerts,
            lakay.compliance.edd-triggers
   - Redis: updated feature cache
```

### 4.2 Data Pipeline Flow (Near-Real-Time)

```
1. Events (from consumers and Lakay output topics)
        |
        v
2. Bronze Layer (BronzeIngestionBuffer)
   - Buffer events in memory by event_type
   - Flush to MinIO as Parquet when:
     - Buffer reaches 1,000 events, OR
     - 60 seconds have elapsed since last flush
   - Add metadata: _ingested_at, _source_topic, _partition, _offset
   - Store full raw JSON (_raw_json column) for immutability
   - Record partition metadata in PostgreSQL
        |
        v
3. Silver Layer (SilverProcessor)
   - Read bronze Parquet partitions
   - Run quality checks (schema validation, null checks)
   - Deduplicate by (event_id, timestamp)
   - Tokenize PII fields (HMAC-SHA256 deterministic tokens)
   - Write clean events to silver/ in MinIO
   - Write rejected events to silver/_rejected/ (dead-letter)
   - Log quality metrics to PostgreSQL (SilverQualityLog)
   - Alert on high rejection rates (> 10% threshold)
        |
        v
4. Gold Layer (GoldProcessor)
   - Read silver Parquet partitions
   - Apply aggregation functions per dataset:
     - daily-transaction-summary
     - circle-lifecycle-summary
     - user-risk-dashboard
     - compliance-reporting
     - platform-health
     - haiti-corridor-analytics
   - Write aggregated Parquet to gold/ in MinIO
   - Update dataset metadata in PostgreSQL (GoldDatasetMeta)
```

### 4.3 Synchronous Scoring Flow (API)

```
1. Client (Trebanx backend) sends POST request
        |
        v
2. FastAPI Route (e.g., POST /fraud/score)
   - Request validation via Pydantic v2
        |
        v
3. Domain Module
   - Feature computation (historical lookups)
   - Rule/model evaluation
   - Score persistence (PostgreSQL)
   - Alert generation (if thresholds exceeded)
   - Kafka alert publishing (async, non-blocking)
        |
        v
4. Response returned to client (< 200ms target for fraud scoring)
```

---

## 5. Technology Stack

### Core

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Language | Python | 3.12 | Primary runtime |
| Web Framework | FastAPI | >= 0.115.0 | Async REST API with auto-generated OpenAPI docs |
| ASGI Server | uvicorn | >= 0.30.0 | High-performance async server |
| Database | PostgreSQL | 16 | Primary state store (scores, alerts, compliance, pipeline metadata) |
| Database Driver | asyncpg | >= 0.30.0 | Async PostgreSQL driver |
| ORM | SQLAlchemy | >= 2.0.35 (async) | Database abstraction with async session management |
| Migrations | Alembic | >= 1.13.0 | Schema migrations |
| Cache / Features | Redis | 7 (alpine) | Feature caching, session data, real-time feature store |
| Redis Client | redis-py | >= 5.1.0 | Async Redis client |
| Message Broker | Apache Kafka | Confluent 7.5.0 | Event streaming (input and output) |
| Kafka Client | aiokafka | >= 0.11.0 | Async Kafka consumer/producer |
| Object Storage | MinIO | latest | S3-compatible data lake for bronze/silver/gold layers |
| S3 Client | boto3 | >= 1.35.0 | MinIO/S3 interaction |

### ML / Data Science

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| ML Registry | MLflow | >= 2.15.0 (image: v2.19.0) | Model versioning, artifact storage, experiment tracking |
| Gradient Boosting | XGBoost | >= 2.1.0 | Primary fraud detection model |
| Classical ML | scikit-learn | >= 1.5.0 | Preprocessing, evaluation, baseline models |
| Feature Store | Feast | interface ready | Stub implementation with Feast-compatible interface |
| Data Format | Apache Parquet | via pyarrow >= 17.0.0 | Columnar storage for data lake |
| DataFrames | pandas | >= 2.2.0 | Data manipulation in pipeline and aggregations |
| Numerics | NumPy | >= 2.1.0 | Numerical computation (drift detection, scoring) |

### Observability and Quality

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Logging | structlog | >= 24.4.0 | Structured JSON logging throughout |
| Validation | Pydantic v2 | >= 2.9.0 | Request/response model validation |
| Schema Validation | jsonschema | >= 4.23.0 | Event schema validation against trebanx-contracts |
| Settings | pydantic-settings | >= 2.5.0 | Environment variable-based configuration |
| Configuration | PyYAML | >= 6.0.0 | YAML configuration files |

### Testing

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Test Framework | pytest | >= 8.3.0 | Unit and integration testing |
| Async Testing | pytest-asyncio | >= 0.24.0 | Async test support (auto mode) |
| Coverage | pytest-cov | >= 5.0.0 | Code coverage reporting |
| HTTP Testing | httpx | >= 0.27.0 | Async HTTP client for API testing |
| Test Data | Faker | >= 30.0.0 | Realistic test data generation |
| Linting | Ruff | >= 0.6.0 | Fast Python linter and formatter |
| Type Checking | mypy | >= 1.11.0 | Static type analysis (strict mode) |

---

## 6. Design Decisions and Rationale

### 6.1 Why FastAPI

FastAPI was selected as the web framework for the following reasons:

- **Async-native**: Built on Starlette and ASGI, it supports `async/await`
  throughout, which is critical for non-blocking Kafka consumption, database
  queries, and Redis lookups within the same process.
- **Automatic OpenAPI documentation**: FastAPI generates interactive API docs
  from Pydantic models, reducing documentation drift and enabling Trebanx
  integration teams to explore the API without separate doc maintenance.
- **Pydantic integration**: Request and response models are validated
  automatically, catching malformed requests before they reach domain logic.
- **Lifespan management**: The lifespan context manager pattern allows clean
  startup (database init, Kafka consumer launch) and shutdown (consumer
  graceful stop).

### 6.2 Why Feast (Feature Store Interface)

- **Industry standard**: Feast is the most widely adopted open-source feature
  store, with native support for online (Redis) and offline (Parquet/BigQuery)
  serving.
- **Training-serving skew prevention**: A feature store ensures that the same
  feature definitions are used during model training and real-time inference,
  eliminating a common source of silent model degradation.
- **Current approach**: The codebase uses a stub `FeatureStore` class
  (`src/features/store.py`) with the same interface that Feast exposes. This
  allows domain modules to program against a stable interface while the full
  Feast integration is completed in a future phase.

### 6.3 Why MLflow

- **Model versioning**: MLflow's model registry provides named model versions
  with stage transitions (None -> Staging -> Production -> Archived), which
  maps directly to the champion/challenger deployment pattern used by the
  `ModelRouter`.
- **A/B routing**: The `ModelRouter` loads champion (Production) and challenger
  (Staging) models from MLflow and routes traffic with deterministic
  user-based hashing — no separate experimentation platform needed.
- **Artifact storage**: MLflow stores model artifacts in MinIO
  (`s3://mlflow-artifacts`), keeping all binary assets in the same
  S3-compatible infrastructure.
- **Experiment tracking**: Training runs, hyperparameters, and evaluation
  metrics are logged to MLflow for auditability and reproducibility.

### 6.4 Why Gradient Boosted Trees Over Neural Networks

- **Interpretability for compliance**: Financial regulators require
  explainable model decisions. GBT models (XGBoost) produce feature
  importance rankings and support SHAP-based explanations, which are
  necessary for SAR narratives and audit responses.
- **Strong tabular performance**: For structured/tabular data (transaction
  amounts, velocities, geo-features), GBTs consistently match or exceed
  neural network performance with less tuning.
- **Lower resource requirements**: GBT inference is CPU-only and completes
  in single-digit milliseconds, enabling in-process scoring without GPU
  infrastructure or a separate inference server.
- **Smaller training datasets**: Financial fraud datasets are typically
  small and highly imbalanced. GBTs handle this better than deep learning
  approaches that require large, balanced datasets.

### 6.5 Why Apache Kafka

- **Event-driven architecture**: Trebanx's backend follows an event sourcing
  pattern where all state changes are emitted as domain events. Kafka is the
  natural fit for consuming these events with consumer groups, partition-based
  parallelism, and at-least-once delivery guarantees.
- **Bidirectional communication**: Lakay both consumes from Trebanx topics
  (5 input topics) and produces to its own topics (5 output topics for
  alerts, tier changes, ATO alerts, compliance alerts, and EDD triggers),
  creating a clean event-driven contract between services.
- **Backpressure handling**: Kafka's consumer group protocol and offset
  management allow Lakay to process events at its own pace without data loss.
- **Data pipeline integration**: Kafka topics feed directly into the bronze
  layer of the data pipeline, providing a unified ingestion path.

### 6.6 Why MinIO

- **S3-compatible**: MinIO implements the S3 API, allowing the codebase to
  use boto3 for storage operations. If Trebanx migrates to AWS, the storage
  layer can switch to native S3 with zero code changes.
- **Self-hosted**: For a fintech handling financial data and PII, self-hosted
  object storage provides full control over data residency and access.
- **Cost-effective**: MinIO runs as a single Docker container in development
  and scales horizontally in production, avoiding cloud storage costs during
  development and testing.
- **Dual use**: MinIO serves both the data lake (bronze/silver/gold Parquet
  files) and MLflow artifact storage (`s3://mlflow-artifacts`).

### 6.7 Why Three-Tier Medallion Architecture (Bronze / Silver / Gold)

- **Bronze (raw)**: Immutable, append-only storage of raw events as received.
  Preserves the full JSON payload (`_raw_json` column) for reprocessing if
  upstream schemas change or bugs are discovered in processing logic.
- **Silver (clean)**: Quality-checked, deduplicated, and PII-tokenized data.
  This layer enforces data contracts (schema validation) and ensures
  downstream consumers never see raw PII. Rejected events are written to a
  dead-letter partition for investigation.
- **Gold (business-ready)**: Pre-computed aggregations optimized for specific
  business questions (daily transaction summaries, circle lifecycle analytics,
  compliance reporting, Haiti corridor analysis). Gold datasets are
  materialized views that avoid expensive ad-hoc aggregations.
- **Standard pattern**: The medallion architecture is the industry standard
  for data lakehouse designs (popularized by Databricks). It provides a clear
  contract between data producers and consumers at each layer.

---

## 7. Deployment Architecture

### 7.1 Development Environment (Docker Compose)

The development environment is fully containerized using Docker Compose
(`docker-compose.yaml`) with the following services:

| Service | Image | Ports | Purpose |
|---------|-------|-------|---------|
| `lakay` | Custom (Dockerfile) | 8000 | Lakay Intelligence FastAPI application |
| `kafka` | confluentinc/cp-kafka:7.5.0 | 9092 | Message broker with auto-created topics |
| `zookeeper` | confluentinc/cp-zookeeper:7.5.0 | 2181 | Kafka coordination |
| `postgres` | postgres:16 | 5432 | Primary database |
| `redis` | redis:7-alpine | 6379 | Feature cache |
| `minio` | minio/minio:latest | 9000, 9001 | Object storage (data lake + MLflow artifacts) |
| `minio-setup` | minio/mc:latest | — | One-shot bucket creation (mlflow-artifacts, lakay-data-lake) |
| `mlflow` | ghcr.io/mlflow/mlflow:v2.19.0 | 5000 | Model registry and experiment tracking |

### 7.2 Process Architecture

Lakay Intelligence runs as a **single FastAPI process** that manages multiple
concerns:

```
  FastAPI Process (uvicorn)
  |
  +-- API Routes (request/response handling)
  |
  +-- Kafka Consumers (asyncio background tasks)
  |   +-- CircleConsumer
  |   +-- TransactionConsumer
  |   +-- SessionConsumer
  |   +-- RemittanceConsumer
  |
  +-- Domain Modules (shared in-process)
  |
  +-- Model Serving (in-process, no separate inference server)
  |
  +-- Data Pipeline (triggered via API or scheduled)
```

Kafka consumers are started as `asyncio.Task` instances within the FastAPI
lifespan context. They share the same event loop as the API routes, which
means:

- No inter-process communication overhead for domain module access.
- Feature store and database sessions are shared efficiently.
- Graceful shutdown: consumers are stopped before the process exits.

### 7.3 Scaling Considerations

Each infrastructure service is **independently scalable**:

- **Lakay application**: Horizontally scale by running multiple instances
  with the same Kafka consumer group. Kafka will rebalance partitions
  across instances automatically (3 partitions per topic by default).
- **PostgreSQL**: Vertical scaling or read replicas for query-heavy
  workloads (dashboards, compliance reports).
- **Redis**: Cluster mode for feature store scaling.
- **MinIO**: Distributed mode for storage scaling.
- **Kafka**: Add brokers and increase partition counts for throughput.

### 7.4 Model Serving Architecture

Model serving is **in-process** — there is no separate inference server
(e.g., no TensorFlow Serving, Triton, or Seldon):

```
  Request ──> ModelRouter ──> ModelServer.predict()
                   |               |
                   |               +-- Load model from MLflow registry
                   |               +-- XGBoost/sklearn .predict() in-process
                   |
                   +-- Deterministic user routing (hash-based A/B)
                   +-- DriftDetector (PSI monitoring per feature)
                   +-- Metrics collection (score, latency per variant)
```

This design was chosen because:

- GBT models are lightweight (CPU-only, single-digit ms inference).
- It avoids the operational overhead of a separate model server.
- Model updates are loaded from MLflow on demand.

---

## 8. Security Architecture

### 8.1 PII Protection

PII is handled with a **defense-in-depth** approach across the data pipeline:

| Layer | PII Treatment |
|-------|--------------|
| Bronze | **Raw PII present** — immutable record of original events. Access restricted to pipeline service account. |
| Silver | **PII tokenized** — deterministic HMAC-SHA256 tokens replace PII fields (user_id, ip_address, device_id, recipient_name, phone, geo-coordinates, etc.). Original values are not stored in silver. |
| Gold | **No PII** — aggregated datasets contain only tokenized identifiers and aggregate metrics. |
| Token Mapping | Token-to-encrypted-value mappings stored in PostgreSQL (`pii_token_mappings` table). Detokenization requires explicit access. Encryption uses a separate key (`PII_ENCRYPTION_KEY`). |

PII fields are defined per event type in `src/pipeline/pii.py`. The tokenizer
processes both top-level fields and nested payload fields (e.g.,
`geo_location.latitude`).

### 8.2 Secrets Management

All secrets and sensitive configuration are managed via **environment
variables**, loaded through `pydantic-settings`:

- `DATABASE_URL` — PostgreSQL connection string
- `KAFKA_BOOTSTRAP_SERVERS` — Kafka broker addresses
- `REDIS_URL` — Redis connection string
- `DATALAKE_ACCESS_KEY` / `DATALAKE_SECRET_KEY` — MinIO credentials
- `PII_TOKEN_SECRET` — HMAC key for PII tokenization
- `PII_ENCRYPTION_KEY` — Encryption key for token mapping storage
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — MLflow S3 access
- `MLFLOW_TRACKING_URI` — MLflow server endpoint

Default values in `src/config.py` are development-only defaults and must be
overridden in production deployments via `.env` files or container
orchestration secrets.

### 8.3 API Security

- **CORS**: Fully restricted in production (`allow_origins=[]`). Wildcard
  origins are only enabled when `DEBUG=true` for local development.
- **Middleware**: All requests pass through `StructuredLoggingMiddleware`
  for audit trail and `global_exception_handler` to prevent stack trace
  leakage.
- **Input validation**: All API inputs are validated through Pydantic v2
  models with strict type checking.

### 8.4 Logging Hygiene

- **Structured JSON logging** via `structlog` throughout all modules.
- **No PII in logs**: Log events use tokenized identifiers, transaction IDs,
  and event IDs — never raw PII values (names, phone numbers, addresses,
  IP addresses).
- **Log levels**: Configurable via `LOG_LEVEL` environment variable.

---

## 9. Performance Characteristics

### 9.1 Latency Targets

| Operation | p95 Target | Notes |
|-----------|-----------|-------|
| Fraud scoring (API) | < 200ms | Feature computation + rules evaluation + DB persist + alert check |
| Session anomaly scoring | < 100ms | Behavioral feature lookup + anomaly detection |
| Feature store lookup | < 10ms | Redis GET with local cache fallback |
| Circle health scoring | < 150ms | Feature retrieval + scoring engine + classification |
| Compliance risk scoring | < 100ms | In-memory rule evaluation + DB persist |

### 9.2 Throughput Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Event ingestion (Kafka) | 1,000 events/sec sustained | Across all consumer topics |
| API requests | 500 req/sec | Mixed read/write workload |
| Bronze flush | Every 60s or 1,000 events | Whichever comes first, per event type |
| Silver processing | 15-minute intervals | Configurable via `DEFAULT_PROCESSING_INTERVAL_SECONDS` |
| Gold refresh | On-demand or daily | Triggered via API or scheduled job |

### 9.3 Resource Characteristics

| Component | Memory Profile | CPU Profile |
|-----------|---------------|-------------|
| Kafka consumers | Low (JSON deserialization) | Low (I/O-bound) |
| Fraud scoring | Moderate (feature vectors in memory) | Moderate (rules + optional ML) |
| Data pipeline | High during flush (Parquet serialization) | Moderate (arrow operations) |
| Model serving | Moderate (loaded model in memory) | Low (GBT inference is fast) |
| Drift detection | Moderate (observation window: up to 50,000 per feature) | Low (periodic PSI computation) |

### 9.4 Data Pipeline Characteristics

| Metric | Value |
|--------|-------|
| Bronze flush interval | 60 seconds (default) |
| Bronze flush batch size | 1,000 events (default) |
| Silver rejection rate alert | > 10% of events rejected |
| Bronze topics monitored | 10 (5 Trebanx input + 5 Lakay output) |
| Gold datasets | 6 materialized aggregations |
| Parquet compression | Snappy |
| Partition scheme | `{layer}/{event_type}/{year}/{month}/{day}/{batch_id}.parquet` |

### 9.5 Model Routing Characteristics

| Metric | Value |
|--------|-------|
| Default champion traffic | 95% |
| Default challenger traffic | 5% |
| Routing method | Deterministic SHA-256 hash of user_id mod 100 |
| Metrics buffer | Last 10,000 routing decisions (in-memory) |
| Drift detection (PSI) | Warning at 0.1, Critical at 0.25 |
| Drift check interval | Every 500 observations |

---

## Appendix A: Kafka Topic Inventory

### Input Topics (from Trebanx)

| Topic | Consumer | Domain |
|-------|----------|--------|
| `trebanx.circle.events` | CircleConsumer | Circles |
| `trebanx.transaction.events` | TransactionConsumer | Fraud |
| `trebanx.user.events` | SessionConsumer | Behavior |
| `trebanx.remittance.events` | RemittanceConsumer | Compliance, Fraud |
| `trebanx.security.events` | (routed by event type) | Compliance |

### Output Topics (from Lakay)

| Topic | Producer | Purpose |
|-------|----------|---------|
| `lakay.fraud.alerts` | FraudScorer | High/critical risk transaction alerts |
| `lakay.circles.tier-changes` | CircleHealthScorer | Circle risk tier transitions |
| `lakay.behavior.ato-alerts` | BehaviorProfiler | Account takeover alerts |
| `lakay.compliance.alerts` | ComplianceMonitor | AML/CFT compliance alerts |
| `lakay.compliance.edd-triggers` | ComplianceMonitor | Enhanced Due Diligence triggers |

## Appendix B: API Route Map

| Prefix | Router Module | Purpose |
|--------|--------------|---------|
| `/health` | `src/api/routes/health.py` | Liveness and readiness probes |
| `/fraud` | `src/api/routes/fraud.py` | Fraud scoring and alert management |
| `/circles` | `src/api/routes/circles.py` | Circle health scoring and analytics |
| `/behavior` | `src/api/routes/behavior.py` | Behavioral profiling and anomaly detection |
| `/compliance` | `src/api/routes/compliance.py` | Compliance monitoring, CTR/SAR, risk scoring |
| `/compliance-reports` | `src/api/routes/compliance_reports.py` | Compliance report generation |
| `/serving` | `src/api/routes/serving.py` | Model management, drift monitoring, A/B routing |
| `/pipeline` | `src/api/routes/pipeline.py` | Data pipeline operations (ingest, process, query) |
| `/experiments` | `src/api/routes/experiments.py` | ML experiment tracking |
| `/dashboards` | `src/api/routes/dashboards.py` | Operational dashboard data |

## Appendix C: Database Table Categories

| Category | Tables | Purpose |
|----------|--------|---------|
| Events | `raw_events` | Idempotent raw event storage from Kafka |
| Fraud | `fraud_scores`, `alerts` | Transaction risk scores and fraud alerts |
| Compliance | CTR/SAR records, compliance cases, risk scores | AML/CFT regulatory records |
| Pipeline | `data_partitions`, `ingestion_checkpoints`, `schema_registry`, `silver_quality_logs`, `gold_dataset_meta` | Pipeline metadata and lineage |
| PII | `pii_token_mappings` | Token-to-encrypted-value reverse mapping |
