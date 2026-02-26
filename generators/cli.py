"""CLI entry point for synthetic data generators.

Usage:
    python -m generators circle --config configs/default_circle.yaml --seed 42 --count 100
    python -m generators transaction --config configs/default_transaction.yaml --count 10000
    python -m generators session --config configs/default_session.yaml --count 5000
    python -m generators remittance --config configs/default_remittance.yaml --count 5000
"""

import argparse
import json
import sys
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser(description="Lakay Intelligence synthetic data generators")
    parser.add_argument(
        "generator",
        choices=["circle", "transaction", "session", "remittance"],
        help="Which generator to run",
    )
    parser.add_argument("--config", type=str, required=True, help="Path to YAML config file")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument(
        "--count", type=int, default=100, help="Number of primary entities to generate"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="stdout",
        choices=["stdout", "file", "kafka"],
        help="Output destination",
    )
    parser.add_argument("--output-file", type=str, default=None, help="Output file path")

    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    if args.generator == "circle":
        from .circle_generator import CircleGenerator

        gen = CircleGenerator(config=config, seed=args.seed)
        events = gen.generate(num_circles=args.count)
    elif args.generator == "transaction":
        from .transaction_generator import TransactionGenerator

        gen = TransactionGenerator(config=config, seed=args.seed)
        events = gen.generate(num_transactions=args.count)
    elif args.generator == "session":
        from .session_generator import SessionGenerator

        gen = SessionGenerator(config=config, seed=args.seed)
        events = gen.generate(num_sessions=args.count)
    elif args.generator == "remittance":
        from .remittance_generator import RemittanceGenerator

        gen = RemittanceGenerator(config=config, seed=args.seed)
        events = gen.generate(num_remittances=args.count)
    else:
        print(f"Unknown generator: {args.generator}", file=sys.stderr)
        sys.exit(1)

    if args.output == "stdout":
        for event in events:
            print(json.dumps(event, default=str))
    elif args.output == "file":
        output_path = args.output_file or f"output/{args.generator}_events.jsonl"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            for event in events:
                f.write(json.dumps(event, default=str) + "\n")
        print(f"Wrote {len(events)} events to {output_path}", file=sys.stderr)
    elif args.output == "kafka":
        print("Kafka output not yet implemented. Use stdout or file.", file=sys.stderr)
        sys.exit(1)

    print(f"Generated {len(events)} events", file=sys.stderr)
