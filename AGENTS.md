# Repository Rules

- Use `uv run python3` for Python commands. Do not use pip.
- Keep credentials, `.env`, raw email, Notion payload caches, and tracking URLs out of Git.
- GNU Stow manages only the repository's `hermes/scripts/` package into `~/.hermes/scripts/`, using `--no-folding`. The cron entrypoints `job-scan-status.sh` and `cron-failure-watch.py` are excluded from Stow and copied because Hermes requires them to resolve inside the scripts directory. Skills, legacy cache entrypoints, and OpenCLI files remain individually linked by `tools/install-runtime.sh`.
- The installer targets the default profile and must not inherit `HERMES_HOME`; use `HERMES_CUSTOM_HERMES_HOME` only when another target is explicitly requested. A linked Git worktree is never a valid runtime source. When invoking the installer from one, set `HERMES_CUSTOM_SOURCE_ROOT` to the absolute canonical-checkout path.
- Do not commit mutable Hermes state, cron output, OpenCLI traces, generated job notes, or backfill data. Reusable utility source belongs under `hermes/scripts/backfill/`; only its legacy runtime entrypoint may live in `~/.hermes/cache/` as a symlink.
- Run `bash tools/verify.sh` after changes. Use `--live` only when the required environment and services are available.
- After the initial repository commit, make code changes in focused worktrees under this repository's `.worktrees/` directory, never directly on `main` or in a sibling/parent worktree directory.
