.PHONY: help install run test lint typecheck format security load-test benchmark up down clean

help:
	@echo "Shortify Engineering Automation Commands:"
	@echo "  make install     - Install local python dependencies in editable mode"
	@echo "  make run         - Run FastAPI local development server (uvicorn)"
	@echo "  make test        - Run test suite with pytest"
	@echo "  make lint        - Run Ruff lint checks"
	@echo "  make format      - Run Ruff format check"
	@echo "  make typecheck   - Run mypy strict type checks"
	@echo "  make security    - Run Bandit and pip-audit security scans"
	@echo "  make load-test   - Run Locust load test headless"
	@echo "  make benchmark   - Run automated benchmark suite"
	@echo "  make up          - Start all Docker Compose services"
	@echo "  make down        - Stop all Docker Compose services"
	@echo "  make clean       - Remove caches and build artifacts"

install:
	python -m pip install --upgrade pip
	pip install -e ".[dev]"

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest tests/ -v

lint:
	ruff check app tests

format:
	ruff format --check app tests

typecheck:
	mypy app

security:
	bandit -r app
	pip-audit

load-test:
	locust -f load_tests/locustfile.py --headless -u 100 -r 10 --run-time 1m --host http://localhost:8000

benchmark:
	python scripts/run_benchmarks.py

up:
	docker compose up -d

down:
	docker compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
