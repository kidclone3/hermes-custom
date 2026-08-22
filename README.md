# Hermes Custom

Versioned source for local Hermes and OpenCLI customizations. Runtime state, credentials, caches, Notion data, email data, and Obsidian content stay outside this repository.

## Included

- Daily LinkedIn and ITviec email-to-Notion job scanner
- ITviec public-job OpenCLI adapter
- Obsidian job-note and index generation
- Cron status wrapper
- Regression tests
- The job-tracker skill and its Notion job-tracking reference
- Legacy Playwright crawler retained as a diagnostic fallback

## Layout

```text
hermes/
  scripts/                         Runtime scanner, tests, cron wrapper, crawler
  skills/productivity/             Custom skill files used by Hermes
opencli/
  clis/itviec/                     ITviec adapter
  sites/itviec/                    Adapter memory and verification fixture
tools/
  install-runtime.sh               Link repository files into Hermes/OpenCLI
  verify.sh                        Offline checks and optional live smoke checks
```

## Prerequisites

- `uv`
- `opencli` 1.8.6 or newer
- `himalaya`
- Node.js 22 or newer
- `NOTION_API_KEY` available to live scanner runs
- Existing Himalaya `Job` folder and Notion Job Tracking database

The scanner intentionally keeps runtime state at `~/.hermes/state/` and reads secrets from the normal Hermes environment. Do not add `.env`, email exports, Notion response caches, or OpenCLI tracking-link fixtures to this repository.

## Install

```bash
cd /home/delus/Documents/tools/hermes-custom
npm install
bash tools/install-runtime.sh
```

The installer creates symlinks from the active Hermes/OpenCLI paths to this repository. If a destination differs from the repository file, it is backed up under `~/.hermes/backups/hermes-custom/<timestamp>/` before replacement.

The existing Hermes cron job continues to invoke:

```text
~/.hermes/scripts/job-scan-status.sh
```

That path becomes a symlink into this repository, so no cron configuration change is required.

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
