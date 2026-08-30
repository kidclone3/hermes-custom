#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_root="$(mktemp -d -t hermes-custom-install.XXXXXX)"
trap 'rm -rf "$test_root"' EXIT

hermes_home="$test_root/hermes"
opencli_home="$test_root/opencli"

HERMES_CUSTOM_HERMES_HOME="$hermes_home" \
OPENCLI_HOME="$opencli_home" \
  bash "$repo_root/tools/install-runtime.sh" >/dev/null

cron_wrapper="$hermes_home/scripts/job-scan-status.sh"
failure_watchdog="$hermes_home/scripts/cron-failure-watch.py"
scanner="$hermes_home/scripts/job-scan.py"
itviec_adapter="$opencli_home/clis/itviec/job-public-detail.js"

[[ -f "$cron_wrapper" ]]
if [[ -L "$cron_wrapper" ]]; then
  printf 'Cron wrapper must be a regular file inside the Hermes scripts directory: %s\n' "$cron_wrapper" >&2
  exit 1
fi
cmp -s "$repo_root/hermes/scripts/job-scan-status.sh" "$cron_wrapper"

[[ -f "$failure_watchdog" ]]
if [[ -L "$failure_watchdog" ]]; then
  printf 'Cron watchdog must be a regular file inside the Hermes scripts directory: %s\n' "$failure_watchdog" >&2
  exit 1
fi
cmp -s "$repo_root/hermes/scripts/cron-failure-watch.py" "$failure_watchdog"

[[ -L "$scanner" ]]
[[ "$(readlink -f "$scanner")" == "$(readlink -f "$repo_root/hermes/scripts/job-scan.py")" ]]

[[ -L "$itviec_adapter" ]]
[[ "$(readlink -f "$itviec_adapter")" == "$(readlink -f "$repo_root/opencli/clis/itviec/job-public-detail.js")" ]]
OPENCLI_HOME="$opencli_home" opencli validate itviec/job-public-detail >/dev/null

printf 'install-runtime containment and adapter loading test passed.\n'
