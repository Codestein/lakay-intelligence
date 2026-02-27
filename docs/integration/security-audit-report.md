# Security Audit Report

Phase 10 -- Task 10.3: Security audit for Lakay Intelligence.

**Audit Date:** _[fill upon completion]_
**Auditor:** _[fill]_
**Scope:** Lakay Intelligence v0.1.0 -- all API endpoints, data pipeline, PII handling,
dependency chain, and configuration management.

---

## 1. OWASP API Security Top 10 Review (2023)

Category-by-category assessment against the OWASP API Security Top 10.

### API1:2023 -- Broken Object Level Authorization (BOLA)

**Status:** NOT YET IMPLEMENTED -- Requires attention at integration time

**Findings:**
- API endpoints accept user IDs, circle IDs, and transaction IDs as path or body
  parameters without verifying that the authenticated caller owns or has access to
  the referenced object.
- Example: `GET /api/v1/behavior/users/{user_id}/profile` returns the profile for
  any user_id provided.
- Example: `GET /api/v1/circles/{circle_id}/health` returns health data for any circle.

**Required at integration:**
- Implement object-level authorization checks on every endpoint that accepts an
  entity ID.
- Verify that the authenticated user is either the entity owner, a circle member,
  or has an admin role.
- Add authorization middleware or dependency injection that enforces access control
  before business logic executes.

---

### API2:2023 -- Broken Authentication

**Status:** NOT YET IMPLEMENTED -- Requires attention at integration time

**Findings:**
- No authentication mechanism is currently implemented. All endpoints are publicly
  accessible.
- No JWT/OAuth2/API key validation is present in the middleware stack.
- The health endpoint (`GET /health`) is appropriately unauthenticated.

**Required at integration:**
- Integrate with Trebanx authentication service (JWT bearer tokens or OAuth2).
- Add authentication middleware to all `/api/v1/*` endpoints.
- Implement token validation, expiry checks, and refresh token handling.
- Rate-limit authentication-adjacent endpoints (e.g., any future login endpoints).

---

### API3:2023 -- Broken Object Property Level Authorization

**Status:** PARTIAL -- PII tokenization mitigates some exposure

**Findings:**
- API responses may include internal scoring details, raw feature values, and
  metadata that should not be exposed to all callers.
- The PII tokenization pipeline (`src/pipeline/pii.py`) correctly identifies and
  tokenizes sensitive fields before data lake storage, covering: `user_id`,
  `sender_id`, `organizer_id`, `recipient_id`, `email`, `phone`, `ip_address`,
  `device_id`, `full_name`, `recipient_name`, `recipient_phone`, `address`,
  `government_id`, `geo_location.latitude`, `geo_location.longitude`.
- API response filtering (which fields are returned to which caller role) is not
  yet implemented.

**Required at integration:**
- Implement response filtering based on caller role (e.g., compliance officer vs
  regular user vs admin).
- Ensure internal scoring signals and feature store data are not exposed in
  customer-facing responses.

---

### API4:2023 -- Unrestricted Resource Consumption

**Status:** PARTIAL -- Some protections in place

**Findings:**
- The load test harness (`tests/load/harness.py`) exercises the system up to
  2500 RPS with configurable concurrency limits (default: 200 concurrent connections).
- The API server does not currently implement request rate limiting.
- No per-user or per-IP rate limiting is configured.
- The fraud scoring endpoint processes payloads of arbitrary size without explicit
  input size validation beyond schema checks.

**Required at integration:**
- Add rate limiting middleware (per-user, per-IP, per-endpoint).
- Configure request body size limits at the reverse proxy or application level.
- Implement circuit breakers for downstream dependencies (database, Kafka, Redis).
- Set connection pool limits for database (`asyncpg`) and Redis.

---

### API5:2023 -- Broken Function Level Authorization

**Status:** NOT YET IMPLEMENTED -- Requires attention at integration time

**Findings:**
- No role-based access control (RBAC) is implemented.
- Administrative endpoints (e.g., compliance report generation, alert management)
  are accessible without privilege verification.
- The `/api/v1/compliance/risk` endpoint should be restricted to compliance officers.
- The fraud alert listing endpoint should require elevated permissions.

**Required at integration:**
- Define roles: `user`, `compliance_officer`, `admin`, `system`.
- Implement RBAC middleware enforcing role requirements per endpoint.
- Restrict compliance endpoints to compliance officers and admins.
- Restrict fraud alert management to authorized operators.

---

### API6:2023 -- Unrestricted Access to Sensitive Business Flows

**Status:** PASS (by design) -- Scoring is read-only

**Findings:**
- The fraud scoring, circle health, and behavior analysis endpoints are read-only
  scoring operations. They do not modify state in a way that could be abused.
- Transaction flagging and alert generation are event-driven (Kafka consumer side),
  not directly exposed through API mutation endpoints.
- No sensitive business flow (e.g., funds transfer, account modification) is
  directly exposed by the intelligence service.

**Note:** The intelligence service is a downstream analytics consumer. Sensitive
business flows (payments, account changes) are handled by upstream services
(transaction-service, user-service). This assessment applies only to the
intelligence service boundary.

---

### API7:2023 -- Server-Side Request Forgery (SSRF)

**Status:** NOT APPLICABLE

**Findings:**
- The API does not accept URLs or network addresses from user input for
  server-side fetching.
- The data lake (MinIO/S3) connection uses a hardcoded endpoint configured via
  environment variable (`DATALAKE_ENDPOINT`), not user-supplied values.
- No webhook or callback URL functionality is implemented.

---

### API8:2023 -- Security Misconfiguration

**Status:** REQUIRES ATTENTION -- Development defaults present

**Findings:**
- **PII secrets use development defaults:** `PII_TOKEN_SECRET` defaults to
  `"lakay-pii-token-secret-dev-only"` and `PII_ENCRYPTION_KEY` defaults to
  `"lakay-encryption-key-dev-only"`. These MUST be overridden in production.
- **MinIO credentials use defaults:** `DATALAKE_ACCESS_KEY` and
  `DATALAKE_SECRET_KEY` default to `"minioadmin"`.
- **Database URL contains default credentials:** The default connection string
  includes `lakay:lakay_dev` credentials.
- **Debug mode** defaults to `False` (correct).
- **CORS configuration** is not documented; verify it is restrictive in production.
- **PII encryption uses XOR-based encoding**, which is explicitly marked as
  development-only in `src/pipeline/pii.py`. Production must use Fernet or AES-GCM.

**Required at integration:**
- Override all secret defaults via environment variables or a secrets manager.
- Replace XOR-based PII encryption with Fernet (symmetric) or AES-256-GCM.
- Verify CORS is configured to allow only the Trebanx frontend origin.
- Ensure debug mode is disabled and log level is set to WARNING or above in production.
- Disable or restrict the Swagger/OpenAPI documentation endpoint in production.

---

### API9:2023 -- Improper Inventory Management

**Status:** PASS

**Findings:**
- The API uses a single versioned prefix (`/api/v1/`) with no deprecated or
  shadow versions.
- All endpoints are documented and exercised by integration tests
  (`tests/integration/test_health_endpoints.py`).
- The health endpoint (`GET /health`) provides version information for
  inventory verification.

---

### API10:2023 -- Unsafe Consumption of APIs

**Status:** NOT APPLICABLE (currently)

**Findings:**
- The intelligence service does not consume external third-party APIs.
- Upstream services (transaction-service, circle-service, user-service,
  remittance-service) are consumed via Kafka events, not direct API calls.
- The Trebanx contract schemas (`contracts_path`) are consumed from a local
  filesystem path, not over the network.

**Note:** If future phases add external API integrations (e.g., sanctions list
providers, identity verification services), this category will need reassessment.

---

## 2. Dependency Scan Results

_Run dependency scanning tools and record results below._

### Tool: `pip-audit` (or `safety`)

```bash
# Run scan
pip-audit --requirement requirements.txt --output json > audit-results.json
```

| Package         | Installed Version | Vulnerability ID | Severity | Fixed In  | Status     |
|-----------------|------------------|------------------|----------|-----------|------------|
| _[fill]_        | _[fill]_         | _[fill]_         | _[fill]_ | _[fill]_  | _[fill]_   |

**Total vulnerabilities found:** _[fill]_
**Critical:** _[fill]_ | **High:** _[fill]_ | **Medium:** _[fill]_ | **Low:** _[fill]_

### Tool: `trivy` (container scan)

```bash
# Scan the Docker image
trivy image lakay-intelligence:latest --format json --output trivy-results.json
```

| Package         | Vulnerability ID | Severity | Fixed In  | Status     |
|-----------------|------------------|----------|-----------|------------|
| _[fill]_        | _[fill]_         | _[fill]_ | _[fill]_  | _[fill]_   |

---

## 3. Secrets Management Verification

### Checklist

| Check                                                          | Status     | Notes                                      |
|----------------------------------------------------------------|------------|--------------------------------------------|
| No hardcoded secrets in source code                            | PASS (dev defaults only) | Dev defaults exist in `src/config.py` and `src/pipeline/pii.py` but are clearly marked as dev-only |
| `.env` file is in `.gitignore`                                 | _[verify]_ | _[check .gitignore]_                       |
| All secrets configurable via environment variables             | PASS       | All secrets use `os.environ.get()` or Pydantic `BaseSettings` |
| PII token secret is not the default in deployment              | _[verify at deploy]_ | Default: `lakay-pii-token-secret-dev-only` |
| PII encryption key is not the default in deployment            | _[verify at deploy]_ | Default: `lakay-encryption-key-dev-only`   |
| Database credentials are not the default in deployment         | _[verify at deploy]_ | Default: `lakay:lakay_dev`                 |
| MinIO/S3 credentials are not the default in deployment         | _[verify at deploy]_ | Default: `minioadmin`                      |
| Secrets are not logged at any log level                        | _[verify]_ | Check structlog configuration              |
| Secrets are not included in API error responses                | _[verify]_ | Check exception handlers                   |
| Secrets are not included in health/status endpoints            | PASS       | Health endpoint returns only version and uptime |

---

## 4. Data Security Verification

### PII Tokenization

**Implementation:** `src/pipeline/pii.py` (`PIITokenizer` class)

| Check                                                          | Status | Evidence                                    |
|----------------------------------------------------------------|--------|---------------------------------------------|
| Deterministic tokenization (same input = same token)           | PASS   | Verified by `test_tokenize_deterministic`   |
| Different values produce different tokens                      | PASS   | Verified by `test_tokenize_different_values` |
| Field-scoped tokens (same value in different fields = different token) | PASS | Verified by `test_tokenize_different_fields` |
| Token format includes field name prefix                        | PASS   | Format: `tok_{field_name}_{hmac_digest[:24]}` |
| Nested PII fields tokenized (e.g., `geo_location.latitude`)   | PASS   | Verified by `test_tokenize_nested_geo`      |
| Null values handled safely (not tokenized)                     | PASS   | Verified by `test_tokenize_handles_none`    |
| Cross-event consistency (same user_id = same token)            | PASS   | Verified by `test_consistency_across_events` |
| Encrypt/decrypt round-trip correctness                         | PASS   | Verified by `test_encrypt_decrypt_roundtrip` |
| Token-to-encrypted mapping persisted to database               | PASS   | `persist_token_mapping()` and `batch_persist_token_mappings()` |
| Detokenization requires database access (access-controlled)    | PASS   | `detokenize()` function queries database    |

**PII fields covered per event type:**

| Event Type               | Tokenized Fields                                                    |
|--------------------------|---------------------------------------------------------------------|
| `transaction-initiated`  | `user_id`, `ip_address`, `device_id`, `recipient_id`, `geo_location.latitude`, `geo_location.longitude` |
| `transaction-completed`  | `user_id`, `ip_address`, `device_id`, `recipient_id`               |
| `transaction-failed`     | `user_id`, `ip_address`, `device_id`                               |
| `transaction-flagged`    | `user_id`, `ip_address`, `device_id`                               |
| `session-started`        | `user_id`, `ip_address`, `device_id`, `geo_location.latitude`, `geo_location.longitude` |
| `session-ended`          | `user_id`, `ip_address`, `device_id`                               |
| `circle-created`         | `organizer_id`                                                     |
| `circle-member-joined`   | `user_id`, `organizer_id`                                          |
| `circle-member-dropped`  | `user_id`                                                          |
| `remittance-initiated`   | `sender_id`, `recipient_name`, `recipient_phone`                   |
| `remittance-completed`   | `sender_id`, `recipient_name`, `recipient_phone`                   |
| `remittance-failed`      | `sender_id`                                                        |

Global PII fields (always tokenized regardless of event type):
`user_id`, `sender_id`, `organizer_id`, `recipient_id`, `email`, `phone`,
`ip_address`, `device_id`, `full_name`, `recipient_name`, `recipient_phone`,
`address`, `government_id`, `geo_location.latitude`, `geo_location.longitude`

### Encryption

| Check                                                          | Status     | Notes                                       |
|----------------------------------------------------------------|------------|---------------------------------------------|
| HMAC-SHA256 used for token generation                          | PASS       | `hmac.new()` with SHA-256 in `_compute_token()` |
| Encryption key is configurable via environment variable        | PASS       | `PII_ENCRYPTION_KEY` env var                |
| Token secret is configurable via environment variable          | PASS       | `PII_TOKEN_SECRET` env var                  |
| Production-grade encryption algorithm used                     | FAIL       | XOR-based encoding used; must be replaced with Fernet or AES-GCM |

### Audit Trail

| Check                                                          | Status     | Notes                                       |
|----------------------------------------------------------------|------------|---------------------------------------------|
| Event ingestion recorded in bronze layer                       | PASS       | `src/pipeline/bronze.py` persists raw events |
| PII token mappings stored in database                          | PASS       | `PIITokenMapping` model with upsert         |
| Compliance alerts include audit metadata                       | PASS       | Alerts include timestamps, correlation IDs  |
| Fraud scoring decisions logged with scoring version            | PASS       | `scoring_version` tracked in circle health; `model_version` in fraud responses |

---

## 5. Open Findings

### Critical Findings

| ID    | Finding                                         | Severity | Component            | Recommendation                               |
|-------|-------------------------------------------------|----------|----------------------|-----------------------------------------------|
| SEC-1 | No authentication on API endpoints              | CRITICAL | `src/api/`           | Implement JWT/OAuth2 authentication before production deployment |
| SEC-2 | PII encryption uses XOR (not production-grade)  | CRITICAL | `src/pipeline/pii.py` | Replace with `cryptography.fernet.Fernet` or AES-256-GCM |

### High Findings

| ID    | Finding                                         | Severity | Component            | Recommendation                               |
|-------|-------------------------------------------------|----------|----------------------|-----------------------------------------------|
| SEC-3 | No object-level authorization (BOLA)            | HIGH     | `src/api/`           | Add ownership/membership checks on all entity endpoints |
| SEC-4 | No role-based access control (RBAC)             | HIGH     | `src/api/`           | Define roles and enforce per-endpoint permissions |
| SEC-5 | No API rate limiting                            | HIGH     | `src/api/`           | Add rate limiting middleware (per-user, per-IP) |
| SEC-6 | Development-default secrets in config           | HIGH     | `src/config.py`      | Enforce non-default secrets in production via startup validation |

### Medium Findings

| ID    | Finding                                         | Severity | Component            | Recommendation                               |
|-------|-------------------------------------------------|----------|----------------------|-----------------------------------------------|
| SEC-7 | No request body size limits                     | MEDIUM   | `src/api/`           | Configure max body size at reverse proxy and application level |
| SEC-8 | CORS configuration not documented               | MEDIUM   | `src/main.py`        | Verify and document CORS policy; restrict to known origins |
| SEC-9 | No circuit breakers for downstream dependencies | MEDIUM   | `src/api/`           | Add circuit breakers for DB, Kafka, Redis calls |

### Low Findings

| ID     | Finding                                         | Severity | Component            | Recommendation                               |
|--------|-------------------------------------------------|----------|----------------------|-----------------------------------------------|
| SEC-10 | Swagger UI may be exposed in production         | LOW      | `src/main.py`        | Disable or protect OpenAPI docs in production |

---

## 6. Remediation Timeline

| Finding | Priority  | Target Phase    | Effort Estimate | Owner    | Status     |
|---------|-----------|-----------------|-----------------|----------|------------|
| SEC-1   | P0        | Pre-production  | 2-3 days        | _[fill]_ | Open       |
| SEC-2   | P0        | Pre-production  | 1 day           | _[fill]_ | Open       |
| SEC-3   | P1        | Pre-production  | 2 days          | _[fill]_ | Open       |
| SEC-4   | P1        | Pre-production  | 2 days          | _[fill]_ | Open       |
| SEC-5   | P1        | Pre-production  | 1 day           | _[fill]_ | Open       |
| SEC-6   | P1        | Pre-production  | 0.5 day         | _[fill]_ | Open       |
| SEC-7   | P2        | Pre-production  | 0.5 day         | _[fill]_ | Open       |
| SEC-8   | P2        | Pre-production  | 0.5 day         | _[fill]_ | Open       |
| SEC-9   | P2        | Post-launch     | 1 day           | _[fill]_ | Open       |
| SEC-10  | P3        | Pre-production  | 0.5 day         | _[fill]_ | Open       |

### Pre-Production Blockers

The following findings MUST be resolved before any production deployment:

1. **SEC-1 (Authentication):** No endpoint should be publicly accessible in production.
2. **SEC-2 (PII Encryption):** The XOR-based encryption provides no real security.
   The `_encrypt_value` and `_decrypt_value` functions in `src/pipeline/pii.py`
   must be replaced with a proper symmetric encryption implementation.

### Integration-Time Considerations

The following items are expected to be resolved when Lakay Intelligence is integrated
with the broader Trebanx platform:

- **Authentication** will be provided by the Trebanx auth service (JWT tokens
  validated by shared middleware).
- **Authorization** will leverage the Trebanx RBAC system and user-circle membership
  data from the circle-service.
- **Rate limiting** will be enforced at the API gateway level (e.g., Kong, Envoy)
  in addition to application-level limits.
- **Secret management** will use the platform secrets manager (e.g., HashiCorp Vault,
  AWS Secrets Manager) rather than environment variables directly.
- **TLS termination** will occur at the load balancer/API gateway, not at the
  application level.

---

## 7. Verification Test Coverage

The following existing test files verify security-relevant behavior:

| Test File                                       | What It Verifies                              |
|-------------------------------------------------|-----------------------------------------------|
| `tests/pipeline/test_pii.py`                    | PII tokenization correctness, determinism, field coverage, encrypt/decrypt roundtrip |
| `tests/unit/test_schema_validation.py`          | Schema validation rejects malformed input     |
| `tests/integration/test_health_endpoints.py`    | API endpoint response structure and status codes |
| `tests/integration/test_schema_compliance.py`   | Generated events conform to Trebanx contract schemas |
| `tests/validation/test_generator_schema_conformance.py` | Generator output conforms to expected schemas |
| `tests/domains/compliance/test_structuring.py`  | Structuring detection thresholds and patterns |
| `tests/domains/compliance/test_ctr.py`          | CTR threshold monitoring                      |
| `tests/domains/compliance/test_sar.py`          | SAR filing trigger verification               |
| `tests/domains/behavior/test_ato.py`            | Account takeover detection logic              |

### Missing Security Tests (Recommended)

| Test Category                    | Description                                      | Priority |
|----------------------------------|--------------------------------------------------|----------|
| Authentication bypass            | Verify endpoints reject unauthenticated requests | P0       |
| Authorization bypass (BOLA)      | Verify users cannot access other users' data     | P0       |
| Input fuzzing                    | Fuzz API inputs with malformed payloads          | P1       |
| SQL injection                    | Verify parameterized queries prevent injection   | P1       |
| Rate limit enforcement           | Verify rate limits are enforced                  | P1       |
| Secret exposure                  | Verify secrets are not leaked in responses/logs  | P1       |
| Encryption strength              | Verify production encryption meets standards     | P0       |
