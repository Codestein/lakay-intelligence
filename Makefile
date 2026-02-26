.PHONY: run test test-unit test-integration lint format typecheck generate docker-up docker-down clean

run:
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v --cov=src --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v -m integration

lint:
	ruff check src/ tests/ generators/

format:
	ruff format src/ tests/ generators/

typecheck:
	mypy src/

generate:
	python -m generators circle --config generators/configs/default_circle.yaml --seed 42 --count 100

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
