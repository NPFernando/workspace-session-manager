#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if command -v gitleaks >/dev/null 2>&1; then
  exec gitleaks detect --source . --no-banner --redact
fi

mapfile -d '' files < <(git ls-files --cached --others --exclude-standard -z)
if (( ${#files[@]} == 0 )); then
  printf '%s\n' 'No files to scan.'
  exit 0
fi

secret_files=()
privacy_files=()
for file in "${files[@]}"; do
  [[ -f "$file" && ! -L "$file" ]] || continue
  case "$file" in
    tests/test_models.py|scripts/secret-scan.sh) ;;
    *) secret_files+=("$file") ;;
  esac
  case "$file" in
    tests/*|docs/current-system-assessment.md) ;;
    *) privacy_files+=("$file") ;;
  esac
done

patterns=(
  'AKIA[0-9A-Z]{16}'
  'gh[pousr]_[A-Za-z0-9_]{30,}'
  'github_pat_[A-Za-z0-9_]{30,}'
  'sk-[A-Za-z0-9_-]{20,}'
  '-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'
  "(api[_-]?key|access[_-]?token|password|passwd|secret)[[:space:]]*[:=][[:space:]]*['\"]?[A-Za-z0-9_+./=-]{16,}"
)

failed=0
for pattern in "${patterns[@]}"; do
  if (( ${#secret_files[@]} > 0 )) \
    && rg --line-number --no-heading --color never --regexp "$pattern" -- "${secret_files[@]}"; then
    failed=1
  fi
done

if (( ${#privacy_files[@]} > 0 )) \
  && rg --line-number --no-heading --color never \
  --regexp '/home/[A-Za-z0-9._-]+/' -- "${privacy_files[@]}"; then
  printf '%s\n' 'Absolute home path found; replace it with a portable path.' >&2
  failed=1
fi

if (( failed != 0 )); then
  printf '%s\n' 'Secret/privacy scan failed.' >&2
  exit 1
fi

printf '%s\n' 'Secret/privacy scan passed (gitleaks not installed; used built-in high-confidence rules).'
