#!/usr/bin/env bash
# Cron wrapper: run the job scanner and emit a concise Telegram-safe status.
# Non-zero exit is intentional: Hermes no_agent cron sends it as a failure alert.
set -uo pipefail

log_file="$(mktemp -t job-scan.XXXXXX.log)"
telegram_file="$(mktemp -t job-scan.XXXXXX.telegram)"
cleanup() { rm -f "$log_file" "$telegram_file"; }
trap cleanup EXIT

if python3 "$HOME/.hermes/scripts/job-scan.py" \
    --telegram-output "$telegram_file" >"$log_file" 2>&1; then
  if [[ -s "$telegram_file" ]]; then
    command cat "$telegram_file"
  else
    summary="$(grep -E '^Summary:' "$log_file" | tail -n 1 || true)"
    printf '📦 **Daily Job Updates**\n%s\n' \
      "${summary:-Completed; scanner produced no summary.}"
  fi
else
  exit_code=$?
  printf 'Daily Job Scan → Notion: FAILED (exit %s)\nLast output:\n%s\n' \
    "$exit_code" \
    "$(tail -n 30 "$log_file")"
  exit "$exit_code"
fi
