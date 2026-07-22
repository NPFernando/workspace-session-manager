#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m venv "$project_dir/.venv"
"$project_dir/.venv/bin/python" -m pip install --upgrade pip
"$project_dir/.venv/bin/python" -m pip install -e "${project_dir}[dev]"

printf 'Development command: %s\n' "$project_dir/.venv/bin/ws-dev"
printf 'No profile, alias, global binary, or existing ws file was changed.\n'
