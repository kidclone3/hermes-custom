#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uv run python3 - "$repo_root" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
job = json.loads((root / 'hermes/cron/weekly-agent-observability.json').read_text())
assert job['schedule'] == 'every sunday 9am'
assert job['script'] == 'agentsview-preflight.sh'
assert job['continuity'] is True
assert job['no_agent'] is False
assert len(job['skills']) == 6
assert 'deliver' not in job and 'failure_deliver' not in job
assert all((root / 'hermes/skills' / skill / 'SKILL.md').exists() or skill in {
    'software-development/agent-runtime-observability', 'autonomous-ai-agents/hermes-agent'
} for skill in job['skills'])
assert (root / 'hermes/scripts' / job['script']).is_file()
print('weekly observability manifest validated')
PY
bash -n "$repo_root/hermes/scripts/agentsview-preflight.sh"
# A mocked healthy endpoint proves the preflight returns without launching a daemon.
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
mkdir -p "$test_root/bin"
printf '#!/bin/sh\nprintf 401\n' >"$test_root/bin/curl"
chmod +x "$test_root/bin/curl"
PATH="$test_root/bin:$PATH" bash "$repo_root/hermes/scripts/agentsview-preflight.sh" |
  grep -q 'AgentsView preflight: available on localhost:8081'
printf 'weekly observability preflight smoke test passed.\n'
