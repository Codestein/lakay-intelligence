# Lakay Intelligence - Synthetic Data Generators

Generators produce realistic synthetic event streams that simulate the Trebanx platform. All generated events conform to the trebanx-contracts JSON Schema definitions.

## Generators

| Generator | Description | Event Types |
|-----------|-------------|-------------|
| `circle` | Full sou-sou circle lifecycle simulation | circle-created, circle-member-joined, circle-contribution-received, etc. |
| `transaction` | Financial transaction patterns with fraud injection | transaction-initiated, transaction-completed, transaction-flagged, etc. |
| `session` | User session behavior with anomaly injection | login-attempt, session-started, user-action-performed, etc. |
| `remittance` | US-Haiti remittance corridor simulation | remittance-initiated, remittance-processing, remittance-completed, etc. |

## Usage

```bash
# Generate 100 circle lifecycles
python -m generators circle --config generators/configs/default_circle.yaml --seed 42 --count 100

# Generate 10,000 transactions
python -m generators transaction --config generators/configs/default_transaction.yaml --seed 42 --count 10000

# Generate 5,000 sessions
python -m generators session --config generators/configs/default_session.yaml --seed 42 --count 5000

# Generate 5,000 remittances
python -m generators remittance --config generators/configs/default_remittance.yaml --seed 42 --count 5000

# Output to file
python -m generators circle --config generators/configs/default_circle.yaml --seed 42 --count 100 --output file --output-file data/circles.jsonl
```

## Configuration

Each generator reads a YAML config file. See `generators/configs/` for examples:

- `default_*.yaml` — Standard generation parameters
- `stress_test.yaml` — High-volume load testing parameters
- `fraud_scenarios.yaml` — Elevated fraud rates for testing detection

## Reproducibility

All generators use seeded random number generation. The same `--seed` value produces identical output, enabling deterministic testing.

## Output Formats

- `stdout` (default) — JSON Lines to standard output
- `file` — JSON Lines to a file (`--output-file path`)
- `kafka` — Direct to Kafka topics (not yet implemented)
