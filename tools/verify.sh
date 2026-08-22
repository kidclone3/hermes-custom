#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="$HOME/.cache/uv"
live=false
if [[ "${1:-}" == "--live" ]]; then
  live=true
elif [[ $# -gt 0 ]]; then
  printf 'Usage: %s [--live]\n' "$0" >&2
  exit 2
fi

for command_name in uv node opencli; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$command_name" >&2
    exit 1
  fi
done

uv run python3 -m py_compile \
  "$repo_root/hermes/scripts/job-scan.py" \
  "$repo_root/hermes/scripts/test_job_scan.py"
uv run python3 -m unittest "$repo_root/hermes/scripts/test_job_scan.py"
node --check "$repo_root/hermes/scripts/job-crawler.mjs"
node --check "$repo_root/opencli/clis/itviec/job-public-detail.js"
opencli validate itviec/job-public-detail
opencli browser hermes-custom-verify verify itviec/job-public-detail --strict-memory

if [[ "$live" == true ]]; then
  if ! command -v himalaya >/dev/null 2>&1; then
    printf 'Missing required command for live verification: himalaya\n' >&2
    exit 1
  fi
  if [[ -z "${NOTION_API_KEY:-${NOTION_API_TOKEN:-}}" ]]; then
    printf 'NOTION_API_KEY or NOTION_API_TOKEN is required for --live\n' >&2
    exit 1
  fi
  uv run python3 "$repo_root/hermes/scripts/job-scan.py" --dry-run
  bash "$repo_root/hermes/scripts/job-scan-status.sh"
fi

printf 'hermes-custom verification passed%s.\n' "$([[ "$live" == true ]] && printf ' (live)' || true)"
