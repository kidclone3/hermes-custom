#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# This repository owns default-profile customizations. Do not inherit a
# session's HERMES_HOME, which may point at another profile.
hermes_home="${HERMES_CUSTOM_HERMES_HOME:-$HOME/.hermes}"
opencli_home="${OPENCLI_HOME:-$HOME/.opencli}"
timestamp="$(date +%Y%m%d-%H%M%S)"
backup_root="$hermes_home/backups/hermes-custom/$timestamp"
backup_count=0
link_count=0
copy_count=0

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

link_file "$repo_root/hermes/scripts/job-scan.py" \
  "$hermes_home/scripts/job-scan.py"
link_file "$repo_root/hermes/scripts/test_job_scan.py" \
  "$hermes_home/scripts/test_job_scan.py"
copy_file "$repo_root/hermes/scripts/job-scan-status.sh" \
  "$hermes_home/scripts/job-scan-status.sh"
link_file "$repo_root/hermes/scripts/job-crawler.mjs" \
  "$hermes_home/scripts/job-crawler.mjs"
for utility in \
  repair_flat_linkedin_notion.py \
  query_linkedin_jobs.py \
  collect_linkedin_job_details.py \
  enrich_linkedin_jobs.py \
  export_linkedin_jobs_to_obsidian.py \
  enrich_itviec_jobs.py; do
  link_file "$repo_root/hermes/scripts/backfill/$utility" \
    "$hermes_home/cache/$utility"
done
link_file "$repo_root/hermes/skills/productivity/job-tracker/SKILL.md" \
  "$hermes_home/skills/productivity/job-tracker/SKILL.md"
link_file "$repo_root/hermes/skills/productivity/notion-operations/references/job-tracking-database.md" \
  "$hermes_home/skills/productivity/notion-operations/references/job-tracking-database.md"
link_file "$repo_root/opencli/clis/itviec/job-public-detail.js" \
  "$opencli_home/clis/itviec/job-public-detail.js"
link_file "$repo_root/opencli/sites/itviec/endpoints.json" \
  "$opencli_home/sites/itviec/endpoints.json"
link_file "$repo_root/opencli/sites/itviec/notes.md" \
  "$opencli_home/sites/itviec/notes.md"
link_file "$repo_root/opencli/sites/itviec/verify/job-public-detail.json" \
  "$opencli_home/sites/itviec/verify/job-public-detail.json"

printf '\nInstalled hermes-custom: %s link(s), %s copy/copies, %s backup(s).\n' \
  "$link_count" "$copy_count" "$backup_count"
if (( backup_count > 0 )); then
  printf 'Backups: %s\n' "$backup_root"
fi
