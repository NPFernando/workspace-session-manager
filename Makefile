.PHONY: format lint type test test-integration check build secret-scan

format:
	ruff format .
	ruff check --fix .

lint:
	ruff format --check .
	ruff check .

type:
	mypy

test:
	pytest -m "not integration"

test-integration:
	WS_RUN_TMUX_INTEGRATION=1 pytest -m integration -q --no-cov

check: lint type test

build:
	python -m build

secret-scan:
	scripts/secret-scan.sh
