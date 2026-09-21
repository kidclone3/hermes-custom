# Hermes Custom

Versioned source for local Hermes and OpenCLI customizations. Runtime state, credentials, caches, Notion data, email data, and Obsidian content stay outside this repository.

## Included

- Daily LinkedIn and ITviec email-to-Notion job scanner
- ITviec public-job OpenCLI adapter
- Obsidian job-note and index generation
- Cron status wrapper
- Failure-only cron watchdog with durable execution checkpoints
- Regression tests
- Versioned LinkedIn/ITviec backfill and repair utilities formerly stored in the runtime cache
- The job-tracker skill and its Notion job-tracking reference
- The agent-observability and use-agentsview skills, plus the signal-model reference
- Legacy Playwright crawler retained as a diagnostic fallback

## Layout

```text
hermes/
  scripts/                         Runtime scanner, tests, cron wrappers/watchdog, crawler
    backfill/                      Versioned operational backfill/repair sources
  skills/                          Custom skill files grouped by category
opencli/
  clis/itviec/                     ITviec adapter
  sites/itviec/                    Adapter memory and verification fixture
tools/
  install-runtime.sh               Stow scripts and link/copy remaining runtime files
  verify.sh                        Offline checks and optional live smoke checks
```

## Prerequisites

- `uv`
- GNU Stow 2.3.1 or newer
- `opencli` 1.8.6 or newer
- `himalaya`
- Node.js 22 or newer
- `NOTION_API_KEY` available to live scanner runs
- Existing Himalaya `Job` folder and Notion Job Tracking database

The scanner intentionally keeps runtime state at `~/.hermes/state/` and reads secrets from the normal Hermes environment. Do not add `.env`, email exports, Notion response caches, or OpenCLI tracking-link fixtures to this repository.

## Install

Install from the canonical checkout:

```bash
cd /home/delus/Documents/tools/hermes-custom
npm ci
bash tools/install-runtime.sh
```

GNU Stow manages exactly the repository's `hermes/scripts/` package into `~/.hermes/scripts/`. The installer uses an explicit source directory and target, `--no-folding`, and ignores `__pycache__` plus generated `.pyc`/`.pyo` bytecode. It runs Stow with isolated temporary `HOME` and working directories, so ambient `.stowrc` options such as `--adopt` or `--simulate` cannot alter installation behavior. It does not Stow `~/.hermes` itself, skills, cache/state paths, or OpenCLI files. Those non-script files retain their existing individual-link behavior.

Two script-package exceptions are always regular copied files: `job-scan-status.sh` and `cron-failure-watch.py`. Hermes cron containment rejects symlink entrypoints because their resolved paths leave `~/.hermes/scripts/`. If a copied destination differs from the repository file, the installer backs it up under `~/.hermes/backups/hermes-custom/<timestamp>/` before replacement.

The default target is `~/.hermes`, even when the current shell has a profile-specific `HERMES_HOME`. A different target must be explicit via `HERMES_CUSTOM_HERMES_HOME=/absolute/path`; this prevents accidental writes into another Hermes profile.

A linked Git worktree is intentionally refused as the source, preventing runtime links from becoming dangling links when the worktree is removed. To test or invoke this installer from a worktree, explicitly select the durable canonical checkout:

```bash
HERMES_CUSTOM_SOURCE_ROOT=/home/delus/Documents/tools/hermes-custom \
  bash tools/install-runtime.sh
```

The override applies to both the Stow package and the remaining individual links. The installer accepts the old `job-scan.py`, `test_job_scan.py`, and `job-crawler.mjs` symlink set as a one-time migration, including links left dangling by a removed worktree. Healthy Stow links are preserved on reruns, and removed legacy links are restored if Stow fails. Copied-entrypoint and other conflicts in `~/.hermes/scripts/` are refused before migration; the installer never uses `stow --adopt`.

The existing Hermes cron job continues to invoke:

```text
~/.hermes/scripts/job-scan-status.sh
```

That path remains a regular file inside the Hermes scripts directory. The canonical checkout remains authoritative; rerun the installer after changing either copied cron entrypoint. No cron configuration change is required.

## Verify

Offline and public-adapter checks:

```bash
npm test
```

Include the Notion scanner dry run and cron wrapper smoke test:

```bash
set -a && . ~/.hermes/.env && set +a
npm run verify:live
```

The OpenCLI adapter can also be exercised directly:

```bash
opencli itviec job-public-detail \
  "https://itviec.com/it-jobs/fresher-junior-senior-ai-agent-engineer-grit-logic-reap-ai-0022" \
  -f json
```

## Runtime data deliberately excluded

- `~/.hermes/.env`
- `~/.hermes/state/`
- `~/.hermes/cache/`
- Raw `.eml` files and tracking URLs
- Notion backfill result files
- Obsidian job notes and indexes
- OpenCLI response traces and generated fixtures

The six legacy backfill utility entrypoints under `~/.hermes/cache/*.py` are symlinks to repository sources. Their generated JSON, JSONL, logs, backups, and payload caches remain unversioned runtime data.
