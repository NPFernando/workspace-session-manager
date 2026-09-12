#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FAST_MODE=0
CI_MODE=0
case "${1:-}" in
  --fast)
    FAST_MODE=1
    shift
    ;;
  --ci)
    CI_MODE=1
    shift
    ;;
  "")
    ;;
  *)
    echo "Usage: scripts/release-checklist.sh [--fast|--ci]" >&2
    exit 2
    ;;
esac
if [[ $# -ne 0 ]]; then
  echo "Usage: scripts/release-checklist.sh [--fast|--ci]" >&2
  exit 2
fi

echo "==> Ruff format check"
uv run ruff format --check .

echo "==> Ruff lint"
uv run ruff check .

echo "==> Type check"
uv run mypy

if [[ "$FAST_MODE" -eq 0 ]]; then
  echo "==> TUI regression suite"
  if ! uv run pytest tests/test_tui.py --no-cov; then
    echo "TUI suite failed; retrying once to deflake timing-sensitive UI tests..."
    uv run pytest tests/test_tui.py --no-cov
  fi

  echo "==> Unit tests (excluding integration, layout snapshot, and TUI suite)"
  uv run pytest -m "not integration and not layout_snapshot" --ignore=tests/test_tui.py --no-cov
else
  echo "==> Fast mode unit tests (excluding integration and layout snapshot)"
  uv run pytest -m "not integration and not layout_snapshot" --no-cov
fi

if [[ "$CI_MODE" -eq 1 ]]; then
  if [[ "${WS_RELEASE_CHECKLIST_RUN_INTEGRATION:-0}" == "1" ]]; then
    echo "==> CI mode integration tests"
    WS_RUN_TMUX_INTEGRATION=1 uv run pytest -m integration -q --no-cov
  else
    echo "==> CI mode integration tests (skipped; set WS_RELEASE_CHECKLIST_RUN_INTEGRATION=1)"
  fi

  if [[ "${WS_RELEASE_CHECKLIST_RUN_LAYOUT:-0}" == "1" ]]; then
    echo "==> CI mode layout snapshot monitor"
    if [[ "${WS_RELEASE_CHECKLIST_STRICT_LAYOUT:-0}" == "1" ]]; then
      uv run pytest -m layout_snapshot -q --no-cov
    else
      if ! uv run pytest -m layout_snapshot -q --no-cov; then
        echo "Layout snapshot monitor reported differences (non-blocking in CI mode)."
      fi
    fi
  else
    echo "==> CI mode layout snapshot monitor (skipped; set WS_RELEASE_CHECKLIST_RUN_LAYOUT=1)"
  fi
fi

echo "==> CI workflow YAML validation"
python3 - <<'PY'
from pathlib import Path
import yaml

workflow_path = Path(".github/workflows/ci.yml")
yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
print("ci.yml is valid YAML")
PY

mode_suffix=""
if [[ "$FAST_MODE" -eq 1 ]]; then
  mode_suffix=" (fast mode)"
elif [[ "$CI_MODE" -eq 1 ]]; then
  mode_suffix=" (ci mode)"
fi

echo
echo "Release checklist passed${mode_suffix}."
echo "Reminder: restart any running 'ws' TUI process before manual UX verification."
