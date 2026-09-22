#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source_root_input="${HERMES_CUSTOM_SOURCE_ROOT:-$repo_root}"
# This repository owns default-profile customizations. Do not inherit a
# session's HERMES_HOME, which may point at another profile.
hermes_home="${HERMES_CUSTOM_HERMES_HOME:-$HOME/.hermes}"
opencli_home="${OPENCLI_HOME:-$HOME/.opencli}"
timestamp="$(date +%Y%m%d-%H%M%S)"
backup_root="$hermes_home/backups/hermes-custom/$timestamp"
backup_count=0
link_count=0
copy_count=0

if [[ -n "${HERMES_CUSTOM_SOURCE_ROOT:-}" && "$source_root_input" != /* ]]; then
  printf 'HERMES_CUSTOM_SOURCE_ROOT must be an absolute path: %s\n' "$source_root_input" >&2
  exit 1
fi
if [[ ! -d "$source_root_input" ]]; then
  printf 'Canonical source root does not exist: %s\n' "$source_root_input" >&2
  exit 1
fi
source_root="$(cd "$source_root_input" && pwd -P)"
if [[ -f "$source_root/.git" ]]; then
  printf 'Refusing linked-worktree source: %s\n' "$source_root" >&2
  printf 'Set HERMES_CUSTOM_SOURCE_ROOT to the absolute path of the canonical checkout.\n' >&2
  exit 1
fi
if [[ ! -d "$source_root/hermes/scripts" ]]; then
  printf 'Missing Stow package: %s\n' "$source_root/hermes/scripts" >&2
  exit 1
fi
if ! command -v stow >/dev/null 2>&1; then
  printf 'GNU Stow is required to install Hermes scripts.\n' >&2
  exit 1
fi
if [[ ! -d "$source_root/node_modules/@jackwener/opencli" ]]; then
  printf 'Missing repository dependencies: %s\nRun npm ci in %s before installing runtime links.\n' \
    "$source_root/node_modules/@jackwener/opencli" "$source_root" >&2
  exit 1
fi

stow_runtime_dir="$(mktemp -d -t hermes-custom-stow.XXXXXX)"
migration_pending=0
migration_destinations=()
migration_targets=()

restore_migration_links() {
  local index destination_path

  for index in "${!migration_destinations[@]}"; do
    destination_path="${migration_destinations[$index]}"
    if [[ -L "$destination_path" ]]; then
      rm -f "$destination_path"
    elif [[ -e "$destination_path" ]]; then
      printf 'Cannot restore migrated link over existing path: %s\n' "$destination_path" >&2
      continue
    fi
    ln -s "${migration_targets[$index]}" "$destination_path"
  done
}

cleanup_install() {
  if (( migration_pending )); then
    restore_migration_links
  fi
  rm -rf "$stow_runtime_dir"
}
trap cleanup_install EXIT

run_stow() (
  cd "$stow_runtime_dir"
  HOME="$stow_runtime_dir" command stow "$@"
)

link_file() {
  local source_path="$1"
  local destination_path="$2"

  if [[ ! -f "$source_path" ]]; then
    printf 'Missing repository file: %s\n' "$source_path" >&2
    return 1
  fi

  mkdir -p "$(dirname "$destination_path")"
  if [[ -L "$destination_path" ]] && [[ "$(readlink -f "$destination_path")" == "$(readlink -f "$source_path")" ]]; then
    printf 'Already linked: %s\n' "$destination_path"
    return 0
  fi

  if [[ -e "$destination_path" || -L "$destination_path" ]]; then
    if [[ -f "$destination_path" ]] && cmp -s "$source_path" "$destination_path"; then
      rm -f "$destination_path"
    else
      local relative_path="${destination_path#/}"
      local backup_path="$backup_root/$relative_path"
      mkdir -p "$(dirname "$backup_path")"
      cp -a "$destination_path" "$backup_path"
      rm -f "$destination_path"
      backup_count=$((backup_count + 1))
      printf 'Backed up: %s -> %s\n' "$destination_path" "$backup_path"
    fi
  fi

  ln -s "$source_path" "$destination_path"
  link_count=$((link_count + 1))
  printf 'Linked: %s -> %s\n' "$destination_path" "$source_path"
}

copy_file() {
  local source_path="$1"
  local destination_path="$2"

  if [[ ! -f "$source_path" ]]; then
    printf 'Missing repository file: %s\n' "$source_path" >&2
    return 1
  fi

  mkdir -p "$(dirname "$destination_path")"
  if [[ -f "$destination_path" ]] && [[ ! -L "$destination_path" ]] && cmp -s "$source_path" "$destination_path"; then
    printf 'Already copied: %s\n' "$destination_path"
    return 0
  fi

  if [[ -e "$destination_path" || -L "$destination_path" ]]; then
    if cmp -s "$source_path" "$destination_path"; then
      rm -f "$destination_path"
    else
      local relative_path="${destination_path#/}"
      local backup_path="$backup_root/$relative_path"
      mkdir -p "$(dirname "$backup_path")"
      cp -a "$destination_path" "$backup_path"
      rm -f "$destination_path"
      backup_count=$((backup_count + 1))
      printf 'Backed up: %s -> %s\n' "$destination_path" "$backup_path"
    fi
  fi

  cp -a "$source_path" "$destination_path"
  copy_count=$((copy_count + 1))
  printf 'Copied: %s <- %s\n' "$destination_path" "$source_path"
}

legacy_scripts=(
  job-scan.py
  test_job_scan.py
  job-crawler.mjs
)

link_target_path() {
  local destination_path="$1"
  local raw_target

  raw_target="$(readlink "$destination_path")"
  if [[ "$raw_target" == /* ]]; then
    readlink -m "$raw_target"
  else
    readlink -m "$(dirname "$destination_path")/$raw_target"
  fi
}

validate_legacy_script_links() {
  local script_name destination_path resolved_path candidate_dir raw_target
  local legacy_dir=""
  local complete_legacy_set=1

  for script_name in "${legacy_scripts[@]}"; do
    destination_path="$hermes_home/scripts/$script_name"
    if [[ ! -L "$destination_path" ]]; then
      complete_legacy_set=0
      continue
    fi
    resolved_path="$(link_target_path "$destination_path")"
    candidate_dir="$(dirname "$resolved_path")"
    if [[ "$candidate_dir" != */hermes/scripts ||
      "$resolved_path" != "$candidate_dir/$script_name" ]]; then
      complete_legacy_set=0
      continue
    fi
    if [[ -z "$legacy_dir" ]]; then
      legacy_dir="$candidate_dir"
    elif [[ "$legacy_dir" != "$candidate_dir" ]]; then
      complete_legacy_set=0
    fi
  done


  for script_name in "${legacy_scripts[@]}"; do
    destination_path="$hermes_home/scripts/$script_name"
    if [[ ! -e "$destination_path" && ! -L "$destination_path" ]]; then
      continue
    fi
    if [[ ! -L "$destination_path" ]]; then
      printf 'Unsafe Stow conflict; refusing to replace: %s\n' "$destination_path" >&2
      return 1
    fi

    raw_target="$(readlink "$destination_path")"
    resolved_path="$(link_target_path "$destination_path")"
    if [[ "$raw_target" != /* &&
      "$resolved_path" == "$source_root/hermes/scripts/$script_name" ]]; then
      continue
    fi
    if [[ "$resolved_path" == "$source_root/hermes/scripts/$script_name" ||
      "$resolved_path" == "$repo_root/hermes/scripts/$script_name" ||
      ( "$complete_legacy_set" == 1 && "$resolved_path" == "$legacy_dir/$script_name" ) ]]; then
      migration_destinations+=("$destination_path")
      migration_targets+=("$raw_target")
      continue
    fi

    printf 'Unsafe Stow conflict; refusing to replace symlink: %s\n' "$destination_path" >&2
    return 1
  done
}

stow_args=(
  "--dir=$source_root/hermes"
  "--target=$hermes_home/scripts"
  --no-folding
  '--ignore=^(job-scan-status\.sh|cron-failure-watch\.py)$'
  '--ignore=(^|/)__pycache__($|/)'
  '--ignore=(^|/).*\.py[co]$'
)

cron_entrypoints=(
  job-scan-status.sh
  cron-failure-watch.py
)
for cron_entrypoint in "${cron_entrypoints[@]}"; do
  cron_source="$source_root/hermes/scripts/$cron_entrypoint"
  cron_destination="$hermes_home/scripts/$cron_entrypoint"
  if [[ ! -f "$cron_source" || -L "$cron_source" ]]; then
    printf 'Cron entrypoint source must be a regular file: %s\n' "$cron_source" >&2
    exit 1
  fi
  if [[ -e "$cron_destination" && ! -f "$cron_destination" && ! -L "$cron_destination" ]]; then
    printf 'Unsafe copied-entrypoint conflict; refusing to replace: %s\n' \
      "$cron_destination" >&2
    exit 1
  fi
done

mkdir -p "$hermes_home/scripts"
if ! run_stow "${stow_args[@]}" \
  '--ignore=^(job-scan\.py|test_job_scan\.py|job-crawler\.mjs)$' \
  --simulate scripts; then
  printf 'Unsafe conflict in Hermes scripts target; no runtime files changed.\n' >&2
  exit 1
fi
validate_legacy_script_links
if (( ${#migration_destinations[@]} > 0 )); then
  migration_pending=1
fi
for legacy_destination in "${migration_destinations[@]}"; do
  rm -f "$legacy_destination"
  printf 'Migrating legacy script link: %s\n' "$legacy_destination"
done
run_stow "${stow_args[@]}" scripts
migration_pending=0

copy_file "$source_root/hermes/scripts/job-scan-status.sh" \
  "$hermes_home/scripts/job-scan-status.sh"
copy_file "$source_root/hermes/scripts/cron-failure-watch.py" \
  "$hermes_home/scripts/cron-failure-watch.py"
for utility in \
  repair_flat_linkedin_notion.py \
  query_linkedin_jobs.py \
  collect_linkedin_job_details.py \
  enrich_linkedin_jobs.py \
  export_linkedin_jobs_to_obsidian.py \
  enrich_itviec_jobs.py; do
  link_file "$source_root/hermes/scripts/backfill/$utility" \
    "$hermes_home/cache/$utility"
done
link_file "$source_root/hermes/skills/productivity/job-tracker/SKILL.md" \
  "$hermes_home/skills/productivity/job-tracker/SKILL.md"
link_file "$source_root/hermes/skills/autonomous-ai-agents/honcho-config-audit/SKILL.md" \
  "$hermes_home/skills/autonomous-ai-agents/honcho-config-audit/SKILL.md"
link_file "$source_root/hermes/skills/productivity/notion-operations/references/job-tracking-database.md" \
  "$hermes_home/skills/productivity/notion-operations/references/job-tracking-database.md"
link_file "$source_root/hermes/skills/software-development/agent-observability/SKILL.md" \
  "$hermes_home/skills/software-development/agent-observability/SKILL.md"
link_file "$source_root/hermes/skills/software-development/agent-observability/references/signal-model.md" \
  "$hermes_home/skills/software-development/agent-observability/references/signal-model.md"
link_file "$source_root/hermes/skills/software-development/use-agentsview/SKILL.md" \
  "$hermes_home/skills/software-development/use-agentsview/SKILL.md"
link_file "$source_root/opencli/clis/itviec/job-public-detail.js" \
  "$opencli_home/clis/itviec/job-public-detail.js"
link_file "$source_root/opencli/sites/itviec/endpoints.json" \
  "$opencli_home/sites/itviec/endpoints.json"
link_file "$source_root/opencli/sites/itviec/notes.md" \
  "$opencli_home/sites/itviec/notes.md"
link_file "$source_root/opencli/sites/itviec/verify/job-public-detail.json" \
  "$opencli_home/sites/itviec/verify/job-public-detail.json"

printf '\nInstalled hermes-custom: scripts managed by GNU Stow; %s additional link(s), %s copy/copies, %s backup(s).\n' \
  "$link_count" "$copy_count" "$backup_count"
if (( backup_count > 0 )); then
  printf 'Backups: %s\n' "$backup_root"
fi
