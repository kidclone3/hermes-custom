#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_root="$(mktemp -d -t hermes-custom-install.XXXXXX)"
trap 'rm -rf "$test_root"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_link_target() {
  local link_path="$1"
  local source_path="$2"

  [[ -L "$link_path" ]] || fail "Expected symlink: $link_path"
  [[ "$(readlink -f "$link_path")" == "$(readlink -f "$source_path")" ]] ||
    fail "Expected $link_path to resolve to canonical source $source_path"
}

assert_regular_copy() {
  local destination_path="$1"
  local source_path="$2"

  [[ -f "$destination_path" ]] || fail "Expected regular file: $destination_path"
  [[ ! -L "$destination_path" ]] || fail "Copied cron entrypoint must not be a symlink: $destination_path"
  cmp -s "$source_path" "$destination_path" ||
    fail "Copied cron entrypoint differs from source: $destination_path"
}

run_installer() {
  local hermes_home="$1"
  local opencli_home="$2"
  local source_root="$3"
  local output_path="$4"

  HERMES_CUSTOM_HERMES_HOME="$hermes_home" \
  HERMES_CUSTOM_SOURCE_ROOT="$source_root" \
  OPENCLI_HOME="$opencli_home" \
    bash "$repo_root/tools/install-runtime.sh" >"$output_path" 2>&1
}

run_installer_from() {
  local working_directory="$1"
  local home_directory="$2"
  local hermes_home="$3"
  local opencli_home="$4"
  local source_root="$5"
  local output_path="$6"

  (
    cd "$working_directory"
    HOME="$home_directory" \
    HERMES_CUSTOM_HERMES_HOME="$hermes_home" \
    HERMES_CUSTOM_SOURCE_ROOT="$source_root" \
    OPENCLI_HOME="$opencli_home" \
      bash "$repo_root/tools/install-runtime.sh"
  ) >"$output_path" 2>&1
}

run_installer_with_stow() {
  local stow_path="$1"
  local hermes_home="$2"
  local opencli_home="$3"
  local source_root="$4"
  local output_path="$5"

  REAL_STOW="$real_stow" \
  PATH="$stow_path:$PATH" \
  HERMES_CUSTOM_HERMES_HOME="$hermes_home" \
  HERMES_CUSTOM_SOURCE_ROOT="$source_root" \
  OPENCLI_HOME="$opencli_home" \
    bash "$repo_root/tools/install-runtime.sh" >"$output_path" 2>&1
}

canonical_source="$test_root/canonical-source"
mkdir -p "$canonical_source"
cp -a "$repo_root/hermes" "$canonical_source/hermes"
cp -a "$repo_root/opencli" "$canonical_source/opencli"
mkdir -p "$canonical_source/node_modules/@jackwener/opencli"
printf 'must not be installed\n' >"$canonical_source/hermes/not-stowed.txt"
mkdir -p "$canonical_source/hermes/scripts/__pycache__"
printf 'generated\n' >"$canonical_source/hermes/scripts/generated.pyc"
printf 'generated\n' >"$canonical_source/hermes/scripts/__pycache__/cached.pyc"

real_stow="$(command -v stow)"
failing_stow_bin="$test_root/failing-stow-bin"
mkdir -p "$failing_stow_bin"
cat >"$failing_stow_bin/stow" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
for argument in "$@"; do
  if [[ "$argument" == --simulate ]]; then
    exec "$REAL_STOW" "$@"
  fi
done
exit 42
EOF
chmod +x "$failing_stow_bin/stow"

adopt_source="$test_root/adopt-source"
adopt_home="$test_root/adopt-home"
adopt_cwd="$test_root/adopt-cwd"
adopt_hermes_home="$test_root/adopt/hermes"
adopt_opencli_home="$test_root/adopt/opencli"
cp -a "$canonical_source" "$adopt_source"
mkdir -p "$adopt_home" "$adopt_cwd" "$adopt_hermes_home/scripts"
printf '%s\n' '--adopt' >"$adopt_home/.stowrc"
printf 'unrelated target content\n' >"$adopt_hermes_home/scripts/test_cron_failure_watch.py"
if run_installer_from "$adopt_cwd" "$adopt_home" "$adopt_hermes_home" \
  "$adopt_opencli_home" "$adopt_source" "$test_root/adopt-rc.log"; then
  fail "HOME .stowrc --adopt must not bypass Stow conflict refusal"
fi
cmp -s "$canonical_source/hermes/scripts/test_cron_failure_watch.py" \
  "$adopt_source/hermes/scripts/test_cron_failure_watch.py" ||
  fail "Hostile --adopt rc setting must not modify canonical source"
[[ "$(cat "$adopt_hermes_home/scripts/test_cron_failure_watch.py")" == 'unrelated target content' ]] ||
  fail "Hostile --adopt rc setting must not replace conflicting target"

simulate_source="$test_root/simulate-source"
simulate_home="$test_root/simulate-home"
simulate_cwd="$test_root/simulate-cwd"
simulate_hermes_home="$test_root/simulate/hermes"
simulate_opencli_home="$test_root/simulate/opencli"
cp -a "$canonical_source" "$simulate_source"
mkdir -p "$simulate_home" "$simulate_cwd"
printf '%s\n' '--simulate' >"$simulate_cwd/.stowrc"
if ! run_installer_from "$simulate_cwd" "$simulate_home" "$simulate_hermes_home" \
  "$simulate_opencli_home" "$simulate_source" "$test_root/simulate-rc.log"; then
  cat "$test_root/simulate-rc.log" >&2
  fail "Installer must ignore a working-directory .stowrc"
fi
assert_link_target "$simulate_hermes_home/scripts/job-scan.py" \
  "$simulate_source/hermes/scripts/job-scan.py"

installer_git_dir="$(git -C "$repo_root" rev-parse --absolute-git-dir)"
installer_common_dir="$(git -C "$repo_root" rev-parse --git-common-dir)"
if [[ "$installer_common_dir" != /* ]]; then
  installer_common_dir="$repo_root/$installer_common_dir"
fi
installer_common_dir="$(readlink -f "$installer_common_dir")"
if [[ "$installer_git_dir" != "$installer_common_dir" ]]; then
  refusal_hermes_home="$test_root/worktree-refusal/hermes"
  refusal_opencli_home="$test_root/worktree-refusal/opencli"
  if HERMES_CUSTOM_HERMES_HOME="$refusal_hermes_home" \
    OPENCLI_HOME="$refusal_opencli_home" \
      bash "$repo_root/tools/install-runtime.sh" >"$test_root/worktree-refusal.log" 2>&1; then
    fail "Installer run from a linked worktree must require an explicit canonical source root"
  fi
  [[ ! -e "$refusal_hermes_home/scripts/job-scan.py" ]] ||
    fail "Worktree refusal must happen before runtime links are changed"
fi

hermes_home="$test_root/clean/hermes"
opencli_home="$test_root/clean/opencli"
run_installer "$hermes_home" "$opencli_home" "$canonical_source" "$test_root/clean-install.log"

scripts_home="$hermes_home/scripts"
[[ -d "$scripts_home" && ! -L "$scripts_home" ]] ||
  fail "Stow target must remain a real directory: $scripts_home"
assert_link_target "$scripts_home/job-scan.py" "$canonical_source/hermes/scripts/job-scan.py"
assert_link_target "$scripts_home/job-crawler.mjs" "$canonical_source/hermes/scripts/job-crawler.mjs"
assert_link_target "$scripts_home/test_cron_failure_watch.py" \
  "$canonical_source/hermes/scripts/test_cron_failure_watch.py"
[[ -d "$scripts_home/backfill" && ! -L "$scripts_home/backfill" ]] ||
  fail "Stow --no-folding must keep the backfill directory real"
assert_link_target "$scripts_home/backfill/README.md" \
  "$canonical_source/hermes/scripts/backfill/README.md"
assert_regular_copy "$scripts_home/job-scan-status.sh" \
  "$canonical_source/hermes/scripts/job-scan-status.sh"
assert_regular_copy "$scripts_home/cron-failure-watch.py" \
  "$canonical_source/hermes/scripts/cron-failure-watch.py"
[[ ! -e "$scripts_home/generated.pyc" && ! -L "$scripts_home/generated.pyc" ]] ||
  fail "Generated bytecode must be ignored by Stow"
[[ ! -e "$scripts_home/__pycache__" && ! -L "$scripts_home/__pycache__" ]] ||
  fail "__pycache__ must be ignored by Stow"
[[ ! -e "$hermes_home/not-stowed.txt" && ! -L "$hermes_home/not-stowed.txt" ]] ||
  fail "Stow must not manage the Hermes home outside its scripts target"

assert_link_target "$hermes_home/cache/query_linkedin_jobs.py" \
  "$canonical_source/hermes/scripts/backfill/query_linkedin_jobs.py"
assert_link_target "$hermes_home/skills/productivity/job-tracker/SKILL.md" \
  "$canonical_source/hermes/skills/productivity/job-tracker/SKILL.md"
assert_link_target "$opencli_home/clis/itviec/job-public-detail.js" \
  "$canonical_source/opencli/clis/itviec/job-public-detail.js"
OPENCLI_HOME="$opencli_home" opencli validate itviec/job-public-detail >/dev/null

scanner_link_before="$(readlink "$scripts_home/job-scan.py")"
scanner_test_link_before="$(readlink "$scripts_home/test_job_scan.py")"
crawler_link_before="$(readlink "$scripts_home/job-crawler.mjs")"
if run_installer_with_stow "$failing_stow_bin" "$hermes_home" "$opencli_home" \
  "$canonical_source" "$test_root/idempotent-failure.log"; then
  fail "Forced final Stow failure must make the installer fail"
fi
[[ "$(readlink "$scripts_home/job-scan.py")" == "$scanner_link_before" ]] ||
  fail "A failed rerun must preserve the healthy scanner Stow link"
[[ "$(readlink "$scripts_home/test_job_scan.py")" == "$scanner_test_link_before" ]] ||
  fail "A failed rerun must preserve the healthy scanner-test Stow link"
[[ "$(readlink "$scripts_home/job-crawler.mjs")" == "$crawler_link_before" ]] ||
  fail "A failed rerun must preserve the healthy crawler Stow link"

legacy_source="$test_root/legacy-source/hermes/scripts"
legacy_hermes_home="$test_root/legacy/hermes"
legacy_opencli_home="$test_root/legacy/opencli"
mkdir -p "$legacy_source" "$legacy_hermes_home/scripts"
for legacy_script in job-scan.py test_job_scan.py job-crawler.mjs; do
  cp "$repo_root/hermes/scripts/$legacy_script" "$legacy_source/$legacy_script"
  ln -s "$legacy_source/$legacy_script" "$legacy_hermes_home/scripts/$legacy_script"
done
rm -rf "$test_root/legacy-source"
legacy_scanner_before="$(readlink "$legacy_hermes_home/scripts/job-scan.py")"
legacy_scanner_test_before="$(readlink "$legacy_hermes_home/scripts/test_job_scan.py")"
legacy_crawler_before="$(readlink "$legacy_hermes_home/scripts/job-crawler.mjs")"
if run_installer_with_stow "$failing_stow_bin" "$legacy_hermes_home" \
  "$legacy_opencli_home" "$canonical_source" "$test_root/legacy-forced-failure.log"; then
  fail "Forced Stow failure during legacy migration must make the installer fail"
fi
[[ "$(readlink "$legacy_hermes_home/scripts/job-scan.py")" == "$legacy_scanner_before" ]] ||
  fail "Failed legacy migration must restore the scanner link"
[[ "$(readlink "$legacy_hermes_home/scripts/test_job_scan.py")" == "$legacy_scanner_test_before" ]] ||
  fail "Failed legacy migration must restore the scanner-test link"
[[ "$(readlink "$legacy_hermes_home/scripts/job-crawler.mjs")" == "$legacy_crawler_before" ]] ||
  fail "Failed legacy migration must restore the crawler link"
if ! run_installer "$legacy_hermes_home" "$legacy_opencli_home" "$canonical_source" \
  "$test_root/legacy-install.log"; then
  cat "$test_root/legacy-install.log" >&2
  fail "Installer must migrate dangling legacy script links"
fi
for migrated_script in job-scan.py test_job_scan.py job-crawler.mjs; do
  assert_link_target "$legacy_hermes_home/scripts/$migrated_script" \
    "$canonical_source/hermes/scripts/$migrated_script"
done

conflict_hermes_home="$test_root/conflict/hermes"
conflict_opencli_home="$test_root/conflict/opencli"
mkdir -p "$conflict_hermes_home/scripts"
printf 'unrelated local file\n' >"$conflict_hermes_home/scripts/job-scan.py"
if run_installer "$conflict_hermes_home" "$conflict_opencli_home" "$canonical_source" \
  "$test_root/conflict-install.log"; then
  fail "Installer must refuse an unsafe conflict in the Stow target"
fi
[[ "$(cat "$conflict_hermes_home/scripts/job-scan.py")" == 'unrelated local file' ]] ||
  fail "Unsafe conflict must remain untouched"
[[ ! -e "$conflict_opencli_home/clis/itviec/job-public-detail.js" ]] ||
  fail "Conflict refusal must occur before unrelated runtime links are changed"

copy_conflict_source="$test_root/copy-conflict-legacy/hermes/scripts"
copy_conflict_hermes_home="$test_root/copy-conflict/hermes"
copy_conflict_opencli_home="$test_root/copy-conflict/opencli"
mkdir -p "$copy_conflict_source" "$copy_conflict_hermes_home/scripts/cron-failure-watch.py"
for legacy_script in job-scan.py test_job_scan.py job-crawler.mjs; do
  cp "$repo_root/hermes/scripts/$legacy_script" "$copy_conflict_source/$legacy_script"
  ln -s "$copy_conflict_source/$legacy_script" \
    "$copy_conflict_hermes_home/scripts/$legacy_script"
done
copy_conflict_scanner_before="$(readlink "$copy_conflict_hermes_home/scripts/job-scan.py")"
if run_installer "$copy_conflict_hermes_home" "$copy_conflict_opencli_home" \
  "$canonical_source" "$test_root/copy-conflict.log"; then
  fail "Installer must reject a copied-entrypoint directory conflict"
fi
[[ -d "$copy_conflict_hermes_home/scripts/cron-failure-watch.py" ]] ||
  fail "Copied-entrypoint conflict must remain untouched"
[[ "$(readlink "$copy_conflict_hermes_home/scripts/job-scan.py")" == \
  "$copy_conflict_scanner_before" ]] ||
  fail "Copied-entrypoint preflight must run before legacy link migration"
[[ ! -e "$copy_conflict_hermes_home/scripts/test_cron_failure_watch.py" ]] ||
  fail "Copied-entrypoint preflight must run before Stow creates links"
[[ ! -e "$copy_conflict_opencli_home/clis/itviec/job-public-detail.js" ]] ||
  fail "Copied-entrypoint preflight must run before unrelated runtime links"

printf 'install-runtime scoped Stow migration test passed.\n'
