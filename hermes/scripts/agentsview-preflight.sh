#!/usr/bin/env bash
set -u

AGENTSVIEW_BIN="${HOME}/.local/bin/agentsview"
READY_PORT=""

is_ready() {
  local port code
  for port in 8081 8080; do
    code="$(curl --connect-timeout 2 --max-time 4 --silent --output /dev/null --write-out '%{http_code}' \
      "http://127.0.0.1:${port}/api/v1/version" 2>/dev/null || true)"
    if [[ "${code}" == "200" || "${code}" == "401" ]]; then
      READY_PORT="${port}"
      return 0
    fi
  done
  return 1
}

wait_until_ready() {
  local attempts="$1" i
  for ((i = 0; i < attempts; i++)); do
    if is_ready; then
      return 0
    fi
    sleep 1
  done
  return 1
}

if is_ready; then
  printf 'AgentsView preflight: available on localhost:%s.\n' "${READY_PORT}"
  exit 0
fi

# A running process may still be completing its initial synchronization.
# Wait before launching another writer and triggering a database-lock failure.
if pgrep -x agentsview >/dev/null 2>&1; then
  if wait_until_ready 60; then
    printf 'AgentsView preflight: existing process became available on localhost:%s.\n' "${READY_PORT}"
    exit 0
  fi
  printf 'AgentsView preflight failed: an agentsview process exists but neither local API endpoint became ready.\n' >&2
  exit 1
fi

if [[ ! -x "${AGENTSVIEW_BIN}" ]]; then
  printf 'AgentsView preflight failed: executable not found at %s.\n' "${AGENTSVIEW_BIN}" >&2
  exit 1
fi

"${AGENTSVIEW_BIN}" serve --background --no-browser

if wait_until_ready 120; then
  printf 'AgentsView preflight: started with agentsview serve and available on localhost:%s.\n' "${READY_PORT}"
  exit 0
fi

printf 'AgentsView preflight failed: agentsview serve did not expose a healthy local API within 120 seconds.\n' >&2
exit 1
