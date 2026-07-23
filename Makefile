.PHONY: setup format lint type test test-integration check build secret-scan

setup:
	uv sync --locked --extra dev

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

type:
	uv run mypy

test:
	uv run pytest -m "not integration"

test-integration:
	WS_RUN_TMUX_INTEGRATION=1 uv run pytest -m integration -q --no-cov

check: lint type test

build:
	uv build

secret-scan:
	scripts/secret-scan.sh
