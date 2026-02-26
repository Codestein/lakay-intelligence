# Lakay Intelligence

AI/ML intelligence microservice for the **Trebanx** fintech platform, serving the Haitian diaspora with digital sou-sou circles (rotating savings groups) and remittances to Haiti.

**Lakay** means "home" in Haitian Creole. It's the internal intelligence layer — it never interacts with end users directly. It observes, analyzes, and recommends.

## Architecture

```
Trebanx Platform                    Lakay Intelligence
┌──────────────┐                   ┌──────────────────┐
│ Circle Svc   │──── Kafka ───────▶│ Circle Consumer   │
│ Transaction  │──── Kafka ───────▶│ Transaction Cons. │──▶ Fraud Scoring
│ User Svc     │──── Kafka ───────▶│ Session Consumer  │──▶ Behavior Analysis
│ Remittance   │──── Kafka ───────▶│ Remittance Cons.  │──▶ Compliance
└──────────────┘                   └──────────────────┘
                                          │
                                   ┌──────▼──────┐
                                   │ PostgreSQL   │
                                   │ Redis        │
                                   └─────────────┘
```

- **Event-driven**: Consumes events from Kafka topics
- **REST API**: FastAPI endpoints for real-time scoring
- **Async**: Fully async with aiokafka + asyncpg

## Prerequisites

- Python 3.12+
- Docker & Docker Compose

## Quick Start

```bash
# Start all services
docker-compose up -d

# Or run locally
pip install ".[dev]"
make run
```

## Development

```bash
# Install dependencies
pip install ".[dev]"

# Run tests
make test

# Lint
make lint

# Format
make format

# Type check
make typecheck
```

## Generators

Synthetic data generators simulate Trebanx events for development and testing:

```bash
# Generate circle lifecycles
python -m generators circle --config generators/configs/default_circle.yaml --seed 42 --count 100

# Generate transactions
python -m generators transaction --config generators/configs/default_transaction.yaml --seed 42 --count 10000
```

See [generators/README.md](generators/README.md) for full documentation.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/ready` | Readiness check (dependencies) |
| POST | `/api/v1/fraud/score` | Score transaction for fraud risk |
| GET | `/api/v1/fraud/alerts` | List recent fraud alerts |
| POST | `/api/v1/circles/health` | Get circle health score |
| POST | `/api/v1/behavior/anomaly` | Detect behavioral anomalies |
| POST | `/api/v1/compliance/risk` | Assess compliance risk |

## Project Structure

```
lakay-intelligence/
├── src/                    # Application source code
│   ├── api/                # FastAPI routes and middleware
│   ├── consumers/          # Kafka event consumers
│   ├── domains/            # Domain logic (fraud, circles, behavior, compliance)
│   ├── db/                 # Database models and migrations
│   ├── features/           # Feature store interface
│   └── shared/             # Shared utilities (schemas, kafka, logging)
├── generators/             # Synthetic data generators
├── tests/                  # Unit, integration, and validation tests
└── docs/                   # Architecture decisions and runbooks
```

## Contributing

1. Create a feature branch from `main`
2. Write code with type hints and tests
3. Run `make lint && make test`
4. Open a pull request
