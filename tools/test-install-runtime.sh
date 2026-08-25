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
scanner="$hermes_home/scripts/job-scan.py"

[[ -f "$cron_wrapper" ]]
if [[ -L "$cron_wrapper" ]]; then
  printf 'Cron wrapper must be a regular file inside the Hermes scripts directory: %s\n' "$cron_wrapper" >&2
  exit 1
fi
cmp -s "$repo_root/hermes/scripts/job-scan-status.sh" "$cron_wrapper"

[[ -L "$scanner" ]]
[[ "$(readlink -f "$scanner")" == "$(readlink -f "$repo_root/hermes/scripts/job-scan.py")" ]]

printf 'install-runtime containment test passed.\n'
